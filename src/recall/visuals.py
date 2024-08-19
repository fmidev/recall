import matplotlib.pyplot as plt


def cmap2hex(cmap):
    """Convert a matplotlib colormap to a list of hex colors."""
    if isinstance(cmap, str):
        cmap = plt.get_cmap(cmap)
    colors = cmap(range(cmap.N))
    return ['#%02x%02x%02x' % (int(r*255), int(g*255), int(b*255)) for r, g, b, _ in colors]

