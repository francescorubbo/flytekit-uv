import subprocess
import tempfile
import shutil
from pathlib import Path

import flytekit
from flytekit.image_spec.image_spec import ImageBuildEngine, ImageSpecBuilder, ImageSpec
from flytekit.loggers import logger


class UvImageBuilder(ImageSpecBuilder):
    """
    Custom ImageSpec builder that uses uv to build a Docker image
    containing all specified dependencies (Flytekit and application).
    """

    @property
    def name(self) -> str:
        return "uv_builder"

    def build_image(self, image_spec: ImageSpec) -> str:
        logger.info(f"Building image with {self.name} for ImageSpec: {image_spec.name}")

        target_image = image_spec.image_name()

        # Create a temporary directory for the build context
        with tempfile.TemporaryDirectory() as temp_dir:
            build_context_path = Path(temp_dir)

            # --- Step 1: Prepare the build context ---
            # Copy source code if source_root is provided (important for uv.lock)
            if image_spec.source_root:
                # Copy the entire source_root to the build context
                shutil.copytree(image_spec.source_root, build_context_path,
                                dirs_exist_ok=True)
                logger.info(
                    f"Copied source_root from {image_spec.source_root} to {build_context_path}")

            # Define the base image
            base_image = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"

            # Construct the Dockerfile content
            dockerfile_content = [
                f"FROM {base_image}",

                # Install Flytekit
                f"ARG FLYTEKIT_VERSION={flytekit.__version__ or '1.16.1'}",
                f"RUN uv pip install --system --no-cache-dir flytekit==${{FLYTEKIT_VERSION}}",

                "WORKDIR /app",
            ]

            # Install application dependencies using uv
            if image_spec.requirements:
                dockerfile_content.append(
                    f"RUN uv pip install --system --no-deps -r {image_spec.requirements}")
            elif image_spec.packages:
                dockerfile_content.append(
                    f"RUN uv pip install --system {' '.join(image_spec.packages)}")

            # Add any apt packages
            if image_spec.apt_packages:
                dockerfile_content.append(
                    "RUN apt-get update && apt-get install -y " + " ".join(
                        image_spec.apt_packages) + " && rm -rf /var/lib/apt/lists/*")

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
                "docker", "build",
                "--tag", target_image,
                "--file", str(dockerfile_path),
                "--platform", image_spec.platform,
                "--push",
                str(build_context_path)
            ]

            logger.info(f"Executing build command: {' '.join(build_command)}")

            try:
                # Execute the Docker build
                result = subprocess.run(build_command, check=True, capture_output=True,
                                        text=True)
                logger.info(f"Docker build stdout:\n{result.stdout}")
                logger.info(f"Docker build stderr:\n{result.stderr}")
                logger.info(f"Successfully built image: {target_image}")
            except subprocess.CalledProcessError as e:
                logger.error(
                    f"Image build failed. Stderr:\n{e.stderr}\nStdout:\n{e.stdout}")
                raise Exception(f"Image build failed: {e.stderr}") from e
            except FileNotFoundError as e:
                logger.error(
                    "Docker command not found. Is Docker installed and in your PATH?")
                raise e

            return target_image


ImageBuildEngine.register("uv_builder", UvImageBuilder())