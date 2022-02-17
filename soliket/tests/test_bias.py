# pytest -k bias -v .

import pytest
import numpy as np

from cobaya.model import get_model
from cobaya.run import run

info = {"params": {
                   "b_lin": 1.1,
                   "H0": 70.,
                   "ombh2": 0.0245,
                   "omch2": 0.1225,
                   "ns": 0.96,
                   "As": 2.2e-9,
                   "tau": 0.05
                   },
        "likelihood": {"one": None},
        "sampler": {"evaluate": None},
        "debug": True
       }


def test_bias_import():
    from soliket.bias import Bias


def test_linear_bias_import():
    from soliket.bias import Linear_bias


def test_linear_bias_model():

    from soliket.bias import Linear_bias

    info["theory"] = {
                   "camb": None,
                   "linear_bias": {"external": Linear_bias}
                   }

    model = get_model(info)  # noqa F841


def test_linear_bias_compute_grid():

    from soliket.bias import Linear_bias

    info["theory"] = {
               "camb": None,
               "linear_bias": {"external": Linear_bias}
               }

    model = get_model(info)  # noqa F841
    model.add_requirements({"Pk_grid": {"z": 0., "k_max": 10.,
                                        "nonlinear": False,
                                        "vars_pairs": ('delta_tot', 'delta_tot')
                                        },
                             "Pk_gg_grid": None,
                             "Pk_gm_grid": None
                            })

    model.logposterior(info['params'])  # force computation of model

    lhood = model.likelihood['one']

    k, z, Pk_mm_lin = lhood.provider.get_Pk_grid(var_pair=('delta_tot', 'delta_tot'),
                                                 nonlinear=False)

    Pk_gg = lhood.provider.get_Pk_gg_grid()
    Pk_gm = lhood.provider.get_Pk_gm_grid()

    assert np.allclose(Pk_mm_lin * info["params"]["b_lin"]**2., Pk_gg)
    assert np.allclose(Pk_mm_lin * info["params"]["b_lin"], Pk_gm)


def test_fastpt_bias_model():

    from soliket.bias import FPTTest, FastPT

    info = {"params": {
        "b_11": 1.,
        "b_12": 1.,
        "b_21": 1.,
        "b_22": 1.,
        "b_s1": 1.,
        "b_s2": 1.,
        "b_3nl1": 1.,
        "b_3nl2": 1.,
        "H0": 70.,
        "ombh2": 0.0245,
        "omch2": 0.1225,
        "ns": 0.96,
        "As": 2.2e-9,
        "tau": 0.05
    },
        "likelihood": {"BiasTest": {"external": FPTTest}},
        "theory": {"camb": None,
                   "FastPT": {"external": FastPT, "zs": [0.6]}
                   },
        "sampler": {"evaluate": None},
        "debug": True,
    }

    model = get_model(info)  # noqa F841
    loglikes, derived = model.loglikes()