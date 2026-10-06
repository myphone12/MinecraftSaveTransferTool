__all__ = ["nbt", "world", "region", "chunk"]
# 显式导入子模块（原为 `from . import *`）。
# Nuitka 编译后对部分初始化包的星号导入不做子模块导入回退，
# 会抛 AttributeError: partially initialized module 'nbt'，故改为显式形式。
from . import nbt, world, region, chunk

# Documentation only automatically includes functions specified in __all__.
# If you add more functions, please manually include them in doc/index.rst.

VERSION = (1, 5, 1)
"""NBT version as tuple. Note that the major and minor revision number are 
always present, but the patch identifier (the 3rd number) is only used in 1.4."""

def _get_version():
    """Return the NBT version as string."""
    return ".".join([str(v) for v in VERSION])
