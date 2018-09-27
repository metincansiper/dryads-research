
from dryadic.learning.pipelines import PresencePipe
from dryadic.learning.selection import SelectMeanVar
from dryadic.learning.stan.base import StanOptimizing
from dryadic.learning.stan.transcripts import *

import numpy as np
from sklearn.preprocessing import StandardScaler, RobustScaler


class OptimModel(BaseTranscripts, StanOptimizing):

    def run_model(self, **fit_params):
        super().run_model(**{**fit_params, **{'iter': 1e6}})


class Base(PresencePipe):
 
    tune_priors = (
        ('fit__alpha', tuple(10 ** np.linspace(-4.5, -1.2, 12))),
        ('fit__gamma', (0.5, 1., 2.)),
        )

    feat_inst = SelectMeanVar(mean_perc=95, var_perc=95)
    norm_inst = StandardScaler()
    fit_inst = OptimModel(model_code=base_model)

    def __init__(self):
        super().__init__([('feat', self.feat_inst), ('norm', self.norm_inst),
                          ('fit', self.fit_inst)])


class Norm_robust(Base):

    norm_inst = RobustScaler()


class Meanvar(Base):

    tune_priors = (
        ('feat__mean_perc', (100./3, 200./3, 80, 90, 99, 100)),
        ('feat__var_perc', (100./3, 200./3, 80, 90, 99, 100)),
        )

    fit_inst = OptimModel(model_code=base_model, alpha=37./13)
