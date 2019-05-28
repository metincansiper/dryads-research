
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable


simil_cmap = LinearSegmentedColormap('SimilCmap', {
    'red': ((0.0,  2.0/3, 2.0/3),
            (1./3,  1.0, 1.0),
            (0.5,  0.365, 0.365),
            (2./3,  0.0, 0.0),
            (1.0,  0.392, 0.392)),
    
    'green': ((0.0,  0.329, 0.329),
              (1./3,  1.0, 1.0),
              (0.5,  0.318, 0.318),
              (2./3,  0.0, 0.0),
              (1.0,  0.729, 0.729)),
 
    'blue': ((0.0,  0.31, 0.31),
             (1./3,  1.0, 1.0),
             (0.5,  0.71, 0.71),
             (2./3,  0.0, 0.0),
             (1.0,  0.416, 0.416))
    })

auc_cmap = LinearSegmentedColormap('aucCmap', {
    'red': ((0.0,  0.608, 0.608),
            (5.0/14, 1.0, 1.0),
            (0.5,  16.0/17, 16.0/17),
            (9.0/14, 0.835, 0.835),
            (1.0,  1.0/37, 1.0/37)),

    'green': ((0.0,  0.0, 0.0),
              (5.0/14, 0.945, 0.945),
              (0.5,  16.0/17, 16.0/17),
              (9.0/14, 0.847, 0.847),
              (1.0,  0.173, 0.173)),
 
    'blue': ((0.0,  0.0, 0.0),
             (5.0/14, 0.945, 0.945),
             (0.5,  16.0/17, 16.0/17),
             (9.0/14, 0.863, 0.863),
             (1.0,  0.4, 0.4))
    })

cor_cmap = ScalarMappable(norm=Normalize(vmin=-1, vmax=1),
                          cmap=auc_cmap).to_rgba

