import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import flytekit
from flytekit.constants import CopyFileDetection
from flytekit.image_spec.default_builder import _copy_lock_files_into_context
from flytekit.image_spec.image_spec import ImageBuildEngine, ImageSpec, ImageSpecBuilder
from flytekit.loggers import logger
from flytekit.tools.ignore import (
    DockerIgnore,
    GitIgnore,
    Ignore,
    IgnoreGroup,
    StandardIgnore,
)
from flytekit.tools.script_mode import ls_files

DEFAULT_PYTHON_VERSION = "3.12"
DEFAULT_UV_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
DEFAULT_FLYTEKIT_VERSION = "1.16.1"


class UVIgnore(Ignore):
    def _is_ignored(self, path: str) -> bool:
        return path.endswith("pyproject.toml") or path.endswith("uv.lock")


class UvImageBuilder(ImageSpecBuilder):
    """
    Custom ImageSpec builder that uses uv to build a Docker image
    containing all specified dependencies (Flytekit and application).
    """

    @property
    def name(self) -> str:
        return "uv"

    def build_image(self, image_spec: ImageSpec) -> str:
        logger.info(f"Building image with {self.name} for ImageSpec: {image_spec.name}")

        target_image = image_spec.image_name()

        source_root = (
            getattr(image_spec, "override_source_root", None) or image_spec.source_root
        )

        # Create a temporary directory for the build context
        copy_commands = []
        with tempfile.TemporaryDirectory() as temp_dir:
            build_context_path = Path(temp_dir)

            if (
                image_spec.source_copy_mode is not None
                and image_spec.source_copy_mode != CopyFileDetection.NO_COPY
            ):
                if not source_root:
                    raise ValueError(
                        f"Field source_root for {image_spec} must be set"
                        " when copy is set"
                    )

                source_path = build_context_path / "src"
                source_path.mkdir(parents=True, exist_ok=True)
                ignores = [GitIgnore, DockerIgnore, StandardIgnore]
                if image_spec.packages:
                    ignores.append(UVIgnore)
                ignore = IgnoreGroup(
                    source_root,
                    ignores,
                )

                ls, _ = ls_files(
                    str(source_root),
                    image_spec.source_copy_mode,
                    deref_symlinks=False,
                    ignore_group=ignore,
                )

                for file_to_copy in ls:
                    rel_path = os.path.relpath(file_to_copy, start=str(source_root))
                    Path(source_path / rel_path).parent.mkdir(
                        parents=True, exist_ok=True
                    )
                    shutil.copy(
                        file_to_copy,
                        source_path / rel_path,
                    )

                copy_commands.append("COPY --chown=flytekit ./src /root")

            if image_spec.copy:
                for src in image_spec.copy:
                    src_path = Path(src)

                    if src_path.is_absolute() or ".." in src_path.parts:
                        raise ValueError(
                            "Absolute paths or paths with '..' "
                            "are not allowed in COPY command."
                        )

                    dst_path = build_context_path / src_path
                    dst_path.parent.mkdir(parents=True, exist_ok=True)

                    if src_path.is_dir():
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                        copy_commands.append(
                            f"COPY --chown=flytekit {src_path.as_posix()} /root/{src_path.as_posix()}/"  # noqa: E501
                        )
                    else:
                        shutil.copy(src_path, dst_path)
                        copy_commands.append(
                            f"COPY --chown=flytekit {src_path.as_posix()} /root/{src_path.parent.as_posix()}/"  # noqa: E501
                        )

            # Define the base image
            base_image = DEFAULT_UV_IMAGE
            if image_spec.base_image:
                raise NotImplementedError(
                    f"Only support default uv image {image_spec.base_image} for now"
                )

            # Construct the Dockerfile content
            dockerfile_content = [
                f"FROM {base_image}",
                "WORKDIR /root",
            ]

            # Add any apt packages
            if image_spec.apt_packages:
                dockerfile_content.append(
                    "RUN apt-get update && apt-get install -y "
                    + " ".join(image_spec.apt_packages)
                    + " && rm -rf /var/lib/apt/lists/*"
                )

            # Set user defined env vars
            if image_spec.env:
                envs = " ".join(f"{k}={v}" for k, v in image_spec.env.items())
                dockerfile_content.append(f"ENV {envs}")

            # Set up uv
            uv_cache_mount = "--mount=type=cache,target=/root/.cache/uv"
            dockerfile_content.extend(
                [
                    "ENV UV_COMPILE_BYTECODE=1",
                    "ENV UV_LINK_MODE=copy",
                ]
            )

            pip_secret_mount = ""
            if image_spec.pip_secret_mounts:
                for secret_id, secret_env in image_spec.pip_secret_mounts:
                    pip_secret_mount += (
                        f"--mount=type=secret,id={secret_id},env={secret_env} "
                    )

            # Install application dependencies using uv
            uv_config_mount = ""
            if image_spec.requirements:
                requirement_basename = os.path.basename(image_spec.requirements)
                if requirement_basename == "uv.lock":
                    _copy_lock_files_into_context(
                        image_spec,
                        "uv.lock",
                        build_context_path,
                    )
                    uv_config_mount = (
                        "--mount=type=bind,source=uv.lock,target=uv.lock "
                        "--mount=type=bind,source=pyproject.toml,target=pyproject.toml"
                    )
                    copy_commands.append(
                        "COPY --chown=flytekit ./uv.lock /root/uv.lock"
                    )
                    copy_commands.append(
                        "COPY --chown=flytekit ./pyproject.toml /root/pyproject.toml"
                    )
                else:
                    raise NotImplementedError(
                        "image_spec.requirements other than uv.lock not supported yet"
                    )
            elif image_spec.packages:
                # Pin python version, if provided, otherwise use DEFAULT_PYTHON_VERSION
                python_version = DEFAULT_PYTHON_VERSION
                if image_spec.python_version:
                    python_version = image_spec.python_version

                dockerfile_content.append(
                    f"RUN uv init --bare --no-workspace --no-config --python {python_version}",  # noqa: E501
                )

                # Add flytekit
                flytekit_version = flytekit.__version__ or DEFAULT_FLYTEKIT_VERSION
                dockerfile_content.append(
                    f"RUN {uv_cache_mount} uv add flytekit=={flytekit_version}",
                )

                uv_add_cmd = (
                    f"RUN {uv_cache_mount} {pip_secret_mount} "
                    f"uv add {' '.join(image_spec.packages)} "
                )
                if image_spec.pip_index:
                    uv_add_cmd += f"--index {image_spec.pip_index} "
                if image_spec.pip_extra_index_url:
                    for extra_index_url in image_spec.pip_extra_index_url:
                        uv_add_cmd += f"--index {extra_index_url} "
                dockerfile_content.append(uv_add_cmd)

            uv_sync_cmd = (
                f"RUN {pip_secret_mount} {uv_cache_mount} {uv_config_mount} "
                "uv sync --locked --no-dev"
            )
            dockerfile_content.extend(
                [
                    f"{uv_sync_cmd} --no-install-project",
                    *copy_commands,
                    uv_sync_cmd,
                    "ENV PATH=/root/.venv/bin:$PATH",
                    "ENTRYPOINT []",
                ]
            )

            # Add any custom commands
            if image_spec.commands:
                for cmd in image_spec.commands:
                    dockerfile_content.append(f"RUN {cmd}")

            # Write the Dockerfile to the build context
            dockerfile_path = build_context_path / "Dockerfile"
            dockerfile_path.write_text("\n".join(dockerfile_content))
            logger.info(f"Generated Dockerfile:\n{dockerfile_path.read_text()}")

            # --- Step 2: Execute the Docker build command ---
            build_command = [
                "docker",
                "build",
                "--tag",
                target_image,
                "--file",
                str(dockerfile_path),
                "--platform",
                image_spec.platform,
                "--push",
                str(build_context_path),
            ]

            if image_spec.pip_secret_mounts:
                for secret_id, secret_env in image_spec.pip_secret_mounts:
                    build_command.extend(
                        ["--secret", f"id={secret_id},env={secret_env}"]
                    )

            logger.info(f"Executing build command: {' '.join(build_command)}")

            try:
                # Execute the Docker build
                subprocess.run(
                    build_command,
                    check=True,
                )
                logger.info(f"Successfully built image: {target_image}")
            except subprocess.CalledProcessError as e:
                logger.error(
                    f"Image build failed. Stderr:\n{e.stderr}\nStdout:\n{e.stdout}"
                )
                raise Exception(f"Image build failed: {e.stderr}") from e
            except FileNotFoundError as e:
                logger.error(
                    "Docker command not found. Is Docker installed and in your PATH?"
                )
                raise e

            return target_image


ImageBuildEngine.register("uv", UvImageBuilder())
