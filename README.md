`flytekit-uv` is a [flytekit](https://github.com/flyteorg/flytekit) plugin providing an alternative backend for ImageSpec based on [uv](https://docs.astral.sh/uv/), removing the dependency on `micromamba`.

# Installation

```bash
pip install flytekit-uv
```
or equivalent for other Python package managers.

# Usage

```python
from flytekit import ImageSpec

image_spec = ImageSpec(
    builder="uv",
    packages=["pandas"],
)

@task(container_image=image_spec)
def task1():
    import pandas
    ...
```
