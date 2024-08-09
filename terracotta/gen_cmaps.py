import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap


def cmap_colors(cmap, N=None):
    """Get the colors of a colormap."""
    if isinstance(cmap, str):
        cmap = plt.get_cmap(cmap)
    if N is None:
        N = cmap.N
    return cmap(np.linspace(0, 1, N))


def cmap2npy(cmap):
    """Convert a matplotlib colormap to a numpy array of RGBA values."""
    if isinstance(cmap, str):
        cmap = plt.get_cmap(cmap)
    colors = cmap_colors(cmap, N=255)
    return np.array([(int(r*255), int(g*255), int(b*255), int(a*255)) for r, g, b, a in colors], dtype=np.uint8)


def cmap_cutoff(cmap, vmin=None, vmax=None, name=None, **kws):
    """Cut off the colormap with transparency."""
    if isinstance(cmap, str):
        cmap = plt.get_cmap(cmap)
    colors = cmap_colors(cmap)
    if vmin is not None:
        colors[:vmin, -1] = 0
    if vmax is not None:
        colors[vmax:, -1] = 0
    if name is None:
        name = cmap.name + '_cut'
    return ListedColormap(colors, name=name, **kws)


def dbz2val(dbz: float) -> int:
    """Convert a dbz to geotiff value."""
    dbz = max(dbz, -32)
    return min(int((dbz + 32) * 2), 255)


def save_cmap(cmap, cmap_dir='/tmp', min_dbz=None):
    """Save a colormap to a numpy file."""
    if isinstance(cmap, str):
        cmap = plt.get_cmap(cmap)
    if min_dbz is not None:
        cmap = cmap_cutoff(cmap, vmin=dbz2val(min_dbz))
    colors = cmap2npy(cmap)
    filename = cmap.name + '_rgba.npy'
    np.save(os.path.join(cmap_dir, filename), colors)


if __name__ == '__main__':
    cmap_dir = os.environ.get('TC_EXTRA_CMAP_FOLDER', '/tmp/prevent/colormaps')
    os.makedirs(cmap_dir, exist_ok=True)
    save_cmap('gist_ncar', cmap_dir=cmap_dir, min_dbz=-10)