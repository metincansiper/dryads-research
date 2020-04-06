
import os
import sys
base_dir = os.path.dirname(__file__)
sys.path.extend([os.path.join(base_dir, '..', '..', '..')])

import argparse
import bz2
from pathlib import Path
import dill as pickle

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
import random

from dryadic.features.mutations import MuType
from HetMan.experiments.subvariant_isolate import cna_mtypes, ex_mtypes
from HetMan.experiments.subvariant_isolate.utils import ExMcomb

from itertools import cycle
from functools import reduce
from operator import add


def compare_muts(*muts_lists):
    return len(set(tuple(sorted(muts_list))
                   for muts_list in muts_lists)) == 1


def calculate_auc(phn_vec, pred_vals, cv_indx=None, use_mean=False):
    test_stat = [len(vals) == 10 for vals in pred_vals]
    use_phn = phn_vec[test_stat]

    if use_phn.all() or not use_phn.any():
        auc_val = 0.5

    else:
        pred_mat = np.vstack(pred_vals.values[test_stat])

        if cv_indx is None:
            cv_indx = list(range(10))
        elif isinstance(cv_indx, int):
            cv_indx = [cv_indx]

        elif not isinstance(cv_indx, list):
            raise TypeError("`cv_indx` must be a list, an integer value, "
                            "or left as None to use all CV iterations!")

        mut_vals = pred_mat[use_phn].T[cv_indx]
        wt_vals = pred_mat[~use_phn].T[cv_indx]

        assert (mut_vals.shape[0] == wt_vals.shape[0]
                == len(cv_indx)), ("Wrong number of CV iterations in "
                                   "classifier output, must be {}!".format(
                                       len(cv_indx)))

        assert mut_vals.shape[1] == use_phn.sum(), (
            "Wrong number of mutated samples in classifier output, must "
            "be {} instead of {}!".format(use_phn.sum(), mut_vals.shape[1])
            )
        assert wt_vals.shape[1] == (~use_phn).sum(), (
            "Wrong number of wild-type samples in classifier output, must "
            "be {} instead of {}!".format((~use_phn).sum(), wt_vals.shape[1])
            )

        if use_mean:
            mut_vals, wt_vals = mut_vals.mean(axis=0), wt_vals.mean(axis=0)

        auc_val = np.greater.outer(mut_vals, wt_vals).mean()
        auc_val += 0.5 * np.equal.outer(mut_vals, wt_vals).mean()

    return auc_val


def calculate_siml(base_mtype, phn_dict, ex_lbl, pred_vals):
    siml_vec = {mtype: 1.0 for mtype in phn_dict}

    none_mean = np.concatenate(pred_vals[~phn_dict[ex_lbl]].values).mean()
    base_mean = np.concatenate(pred_vals[phn_dict[base_mtype]].values).mean()
    cur_diff = base_mean - none_mean

    return {othr_mtype: (np.concatenate(pred_vals[phn].values).mean()
                         - none_mean) / cur_diff
            for othr_mtype, phn in phn_dict.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('use_dir', type=str, default=base_dir)
    args = parser.parse_args()

    # get list of output files from all parallelized jobs
    file_list = tuple(Path(os.path.join(args.use_dir, 'output')).glob(
        "out__cv-*_task*.p"))
    assert (len(file_list) % 40) == 0, "Missing output files detected!"

    task_count = len(file_list) // 40
    out_data = [[None for task_id in range(task_count)]
                for cv_id in range(40)]

    for out_fl in file_list: 
        base_name = out_fl.stem.split('out__')[1]
        cv_id = int(base_name.split('cv-')[1].split('_')[0])
        task_id = int(base_name.split('task-')[1])

        with open(out_fl, 'rb') as f:
            out_data[cv_id][task_id] = pickle.load(f)

    use_clfs = set(out_dict['Clf'] for ols in out_data for out_dict in ols)
    assert len(use_clfs) == 1, ("Each experiment must be run with "
                                "exactly one classifier!")
    use_clf = tuple(use_clfs)[0]

    use_tune = set(out_dict['Clf'].tune_priors for ols in out_data
                   for out_dict in ols)
    assert len(use_tune) == 1, ("Each experiment must be run with "
                                "exactly one set of tuning priors!")

    with bz2.BZ2File(os.path.join(args.use_dir, 'setup',
                                  "cohort-data.p.gz"), 'r') as f:
        cdata = pickle.load(f)

    use_mtree = tuple(cdata.mtrees.values())[0]
    all_mtype = MuType(use_mtree.allkey())
    mut_samps = use_mtree.get_samples()
    shal_samps = dict(cna_mtypes)['Shal'].get_samples(use_mtree)

    with open(os.path.join(args.use_dir, 'setup', "muts-list.p"), 'rb') as f:
        muts_list = pickle.load(f)

    out_dfs = {k: {ex_lbl: [None for cv_id in range(40)]
                   for ex_lbl in ['All', 'Iso', 'IsoShal']}
               for k in ['Pars', 'Time', 'Acc', 'Pred']}

    pred_lists = {ex_lbl: [None for cv_id in range(40)]
                  for ex_lbl in ['All', 'Iso', 'IsoShal']}

    for cv_id, ols in enumerate(out_data):
        for k in out_dfs:
            for ex_lbl in ['All', 'Iso', 'IsoShal']:
                out_dfs[k][ex_lbl][cv_id] = pd.DataFrame({
                    mtype: out_vals[ex_lbl]
                    for out_dict in ols
                    for mtype, out_vals in out_dict[k].items()
                    }).transpose()

        cdata_samps = sorted(cdata.get_samples())
        random.seed((cv_id // 4) * 3901 + 23)
        random.shuffle(cdata_samps)

        cdata.update_split(13101 + 103 * cv_id,
                           test_samps=cdata_samps[(cv_id % 4)::4])

        samps_dict = {'train': cdata.get_train_samples(),
                      'test': cdata.get_test_samples()}

        for ex_lbl in ['All', 'Iso', 'IsoShal']:
            use_muts = out_dfs['Pred'][ex_lbl][cv_id].index
            assert sorted(use_muts) == sorted(muts_list), (
                "Mutations with `{}` predictions for c-v fold <{}> don't "
                "match those enumerated during setup!".format(ex_lbl, cv_id)
                )

            pred_lists[ex_lbl][cv_id] = pd.DataFrame(
                index=use_muts, columns=cdata.get_samples()).applymap(
                    lambda x: [])

            pred_lists[ex_lbl][cv_id][samps_dict['test']] = pd.DataFrame(
                [preds for preds in out_dfs['Pred'][ex_lbl][cv_id].test],
                index=use_muts, columns=samps_dict['test']
                ).applymap(lambda x: [x])

            if 'train' in out_dfs['Pred'][ex_lbl][cv_id]:
                train_mat = out_dfs['Pred'][ex_lbl][cv_id].train[
                    ~out_dfs['Pred'][ex_lbl][cv_id].train.isnull()]

                for mtype, train_preds in train_mat.iteritems():
                    mtype_samps = mtype.get_samples(use_mtree)

                    if ex_lbl == 'Iso':
                        use_samps = mut_samps - mtype_samps
                    elif ex_lbl == 'IsoShal':
                        use_samps = mut_samps - mtype_samps - shal_samps

                    out_samps = sorted(use_samps & set(samps_dict['train']))
                    pred_lists[ex_lbl][cv_id].loc[mtype][out_samps] = [
                        [x] for x in train_preds]

    pred_dfs = {ex_lbl: reduce(add, pred_mats)
                for ex_lbl, pred_mats in pred_lists.items()}
    assert (pred_dfs['All'].applymap(len) == 10).values.all(), (
        "Incorrect number of testing CV scores!")

    pars_dfs = {ex_lbl: pd.concat(out_dfs['Pars'][ex_lbl], axis=1)
                for ex_lbl in ['All', 'Iso', 'IsoShal']}

    for pars_df in pars_dfs.values():
        assert pars_df.shape[1] == (40 * len(use_clf.tune_priors)), (
            "Tuned parameter values missing for some CVs!")

    time_dfs = {ex_lbl: pd.concat(out_dfs['Time'][ex_lbl], axis=1)
                for ex_lbl in ['All', 'Iso', 'IsoShal']}

    for time_df in time_dfs.values():
        assert time_df.shape[1] == 80, (
            "Algorithm fitting times missing for some CVs!")
        assert (time_df.applymap(len) == use_clf.test_count).values.all(), (
            "Algorithm fit times missing for some hyper-parameter values!")

    acc_dfs = {ex_lbl: pd.concat(out_dfs['Acc'][ex_lbl], axis=1)
               for ex_lbl in ['All', 'Iso', 'IsoShal']}

    for acc_df in acc_dfs.values():
        assert acc_df.shape[1] == 120, (
            "Algorithm tuning accuracies missing for some CVs!")
        assert (acc_df.applymap(len) == use_clf.test_count).values.all(), (
            "Algorithm tuning stats missing for some hyper-parameter values!")

    for out_dfs in [pred_dfs, pars_dfs, time_dfs, acc_dfs]:
        for out_df in out_dfs.values():
            assert compare_muts(out_df.index, muts_list), (
                "Mutations for which predictions were made do not match "
                "the list of mutations enumerated during setup!"
                )

    with bz2.BZ2File(os.path.join(args.use_dir, "out-pred.p.gz"), 'w') as fl:
        pickle.dump(pred_dfs, fl, protocol=-1)
    with bz2.BZ2File(os.path.join(args.use_dir, "out-tune.p.gz"), 'w') as fl:
        pickle.dump([pars_dfs, time_dfs, acc_dfs, use_clf], fl, protocol=-1)

    cdata.update_split(test_prop=0)
    train_samps = np.array(cdata.get_train_samples())
    pheno_dict = {mtype: np.array(cdata.train_pheno(mtype))
                  for mtype in muts_list}

    with bz2.BZ2File(os.path.join(args.use_dir, "out-pheno.p.gz"), 'w') as fl:
        pickle.dump(pheno_dict, fl, protocol=-1)

    # calculates AUCs for prediction tasks using scores from all
    # cross-validations concatenated together...
    auc_dicts = {
        ex_lbl: {
            'all': pd.Series(dict(zip(muts_list, Parallel(
                backend='threading', n_jobs=12, pre_dispatch=12)(
                    delayed(calculate_auc)(
                        pheno_dict[mtype],
                        pred_dfs[ex_lbl].loc[mtype, train_samps],
                        )
                    for mtype in muts_list
                    )
                ))),

            # ...and for each cross-validation run considered separately...
            'CV': pd.DataFrame.from_records(
                tuple(zip(cycle(muts_list), Parallel(
                    backend='threading', n_jobs=12, pre_dispatch=12)(
                        delayed(calculate_auc)(
                            pheno_dict[mtype],
                            pred_dfs[ex_lbl].loc[mtype, train_samps],
                            cv_indx=cv_id
                            )
                        for cv_id in range(10) for mtype in muts_list
                        )
                    ))
                ).pivot_table(index=0, values=1, aggfunc=list).iloc[:, 0],

            # ...and finally using the average of predicted scores for each
            # sample across CV runs
            'mean': pd.Series(dict(zip(muts_list, Parallel(
                backend='threading', n_jobs=12, pre_dispatch=12)(
                    delayed(calculate_auc)(
                        pheno_dict[mtype],
                        pred_dfs[ex_lbl].loc[mtype, train_samps],
                        use_mean=True
                        )
                    for mtype in muts_list
                    )
                )))
            }
        for ex_lbl in ['All', 'Iso', 'IsoShal']
        }

    for ex_lbl in ['All', 'Iso', 'IsoShal']:
        auc_dicts[ex_lbl]['CV'].name = None
        auc_dicts[ex_lbl]['CV'].index.name = None

    with bz2.BZ2File(os.path.join(args.use_dir, "out-aucs.p.gz"), 'w') as fl:
        pickle.dump(auc_dicts, fl, protocol=-1)

    random.seed(9903)
    sub_inds = [random.choices([False, True], k=len(cdata.get_samples()))
                for _ in range(50)]

    conf_lists = {
        ex_lbl: {
            'all': pd.DataFrame.from_records(
                tuple(zip(cycle(muts_list), Parallel(
                    backend='threading', n_jobs=12, pre_dispatch=12)(
                        delayed(calculate_auc)(
                            pheno_dict[mtype][sub_indx],
                            pred_dfs[ex_lbl].loc[
                                mtype, train_samps[sub_indx]]
                            )
                        for sub_indx in sub_inds for mtype in muts_list
                        )
                    ))
                ).pivot_table(index=0, values=1, aggfunc=list).iloc[:, 0],

            'mean': pd.DataFrame.from_records(
                tuple(zip(cycle(muts_list), Parallel(
                    backend='threading', n_jobs=12, pre_dispatch=12)(
                        delayed(calculate_auc)(
                            pheno_dict[mtype][sub_indx],
                            pred_dfs[ex_lbl].loc[
                                mtype, train_samps[sub_indx]],
                            use_mean=True
                            )
                        for sub_indx in sub_inds for mtype in muts_list
                        )
                    ))
                ).pivot_table(index=0, values=1, aggfunc=list).iloc[:, 0]
            }
        for ex_lbl in ['All', 'Iso', 'IsoShal']
        }

    for ex_lbl in ['All', 'Iso', 'IsoShal']:
        conf_lists[ex_lbl]['all'].name = None
        conf_lists[ex_lbl]['mean'].name = None
        conf_lists[ex_lbl]['all'].index.name = None
        conf_lists[ex_lbl]['mean'].index.name = None

    with bz2.BZ2File(os.path.join(args.use_dir, "out-conf.p.gz"), 'w') as fl:
        pickle.dump(conf_lists, fl, protocol=-1)

    mcomb_list = {mtype for mtype in muts_list if isinstance(mtype, ExMcomb)}
    for ex_lbl, ex_mtype in ex_mtypes:
        pheno_dict[ex_lbl] = np.array(cdata.train_pheno(all_mtype - ex_mtype))

    siml_lists = {
        ex_lbl: pd.DataFrame(dict(zip(mcomb_list, Parallel(
            backend='threading', n_jobs=12, pre_dispatch=12)(
                delayed(calculate_siml)(
                    mtype, pheno_dict, ex_lbl,
                    pred_dfs[ex_lbl].loc[mtype, train_samps]
                    )
                for mtype in mcomb_list
                )
            )))
        for ex_lbl in ['Iso', 'IsoShal']
        }

    with bz2.BZ2File(os.path.join(args.use_dir, "out-siml.p.gz"), 'w') as fl:
        pickle.dump(siml_lists, fl, protocol=-1)


if __name__ == "__main__":
    main()
