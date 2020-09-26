
from ...experiments.utilities.data_dirs import (
    firehose_dir, syn_root, metabric_dir, baml_dir, ccle_dir,
    gencode_dir, subtype_file, expr_sources
    )

from .beatAML import process_input_datasets as process_baml_datasets
from .tcga import tcga_subtypes
from .tcga import process_input_datasets as process_tcga_datasets
from .tcga import choose_subtypes as choose_tcga_subtypes
from .tcga import parse_subtypes as parse_tcga_subtypes
from .metabric import process_input_datasets as process_metabric_datasets
from .metabric import choose_subtypes as choose_metabric_subtypes
from .metabric import load_metabric_samps
from .ccle import process_input_datasets as process_ccle_datasets

from dryadic.features.data.vep import process_variants
from dryadic.features.cohorts.mut import BaseMutationCohort

import os
import synapseclient
import pandas as pd
import dill as pickle


def get_input_datasets(cohort, expr_source, mut_fields=None):
    data_dict = {data_k: None
                 for data_k in ('expr', 'vars', 'copy', 'annot', 'assembly')}

    syn = synapseclient.Synapse()
    syn.cache.cache_root_dir = syn_root

    if cohort == 'beatAML':
        syn.login()
        data_dict['assembly'] = 'GRCh37'

        if expr_source != 'toil__gns':
            raise ValueError("Only gene-level Kallisto calls are available "
                             "for the beatAML cohort!")

        data_dict.update({
            data_k: baml_data
            for data_k, baml_data in zip(
                ('expr', 'vars', 'annot'),
                process_baml_datasets(baml_dir, gencode_dir, syn,
                                      annot_fields=['transcript'],
                                      mut_fields=mut_fields)
                )
            })

    elif cohort.split('_')[0] == 'METABRIC':
        data_dict['assembly'] = 'GRCh37'

        if expr_source != 'microarray':
            raise ValueError("Only Illumina microarray mRNA calls are "
                             "available for the METABRIC cohort!")

        if '_' in cohort:
            use_types = cohort.split('_')[1]
        else:
            use_types = None

        data_dict.update({
            data_k: mtbc_data
            for data_k, mtbc_data in zip(
                ('expr', 'vars', 'copy', 'annot'),
                process_metabric_datasets(
                    metabric_dir, gencode_dir, use_types,
                    annot_fields=['transcript'], mut_fields=mut_fields
                    )
                )
            })

    elif cohort.split('_')[0] == 'CCLE':
        data_dict['assembly'] = 'GRCh37'

        data_dict.update({
            data_k: ccle_data
            for data_k, ccle_data in zip(
                ('expr', 'vars', 'copy', 'annot'),
                process_ccle_datasets(ccle_dir, gencode_dir, expr_source)
                )
            })

    else:
        syn.login()
        data_dict['assembly'] = 'GRCh37'

        source_info = expr_source.split('__')
        source_base = source_info[0]
        collapse_txs = not (len(source_info) > 1 and source_info[1] == 'txs')

        data_dict.update({
            data_k: tcga_data
            for data_k, tcga_data in zip(
                ('expr', 'vars', 'copy', 'annot'),
                process_tcga_datasets(
                    cohort, expr_source=source_base,
                    var_source='mc3', copy_source='Firehose',
                    expr_dir=expr_sources[source_base], annot_dir=gencode_dir,
                    type_file=subtype_file, collapse_txs=collapse_txs,
                    annot_fields=['transcript'], syn=syn,
                    mut_fields=mut_fields
                    )
                )
            })

    return data_dict


def get_cohort_data(cohort, expr_source, mut_lvls, vep_cache_dir, out_path,
                    use_genes=None):
    data_dict = get_input_datasets(
        cohort, expr_source,
        mut_fields=['Sample', 'Gene', 'Chr', 'Start', 'End',
                    'RefAllele', 'TumorAllele']
        )

    # TODO: how to handle this special case
    if cohort == 'CCLE':
        return BaseMutationCohort(data_dict['expr'], data_dict['vars'],
                                  [('Gene', 'Form')], data_dict['copy'],
                                  data_dict['annot'], leaf_annot=None)

    var_df = pd.DataFrame({'Chr': data_dict['vars'].Chr.astype('int'),
                           'Start': data_dict['vars'].Start.astype('int'),
                           'End': data_dict['vars'].End.astype('int'),
                           'RefAllele': data_dict['vars'].RefAllele,
                           'VarAllele': data_dict['vars'].TumorAllele,
                           'Sample': data_dict['vars'].Sample})

    if isinstance(mut_lvls[0], str):
        var_fields = ['Gene', 'Canonical', 'Location', 'VarAllele']
        cdata_lvls = [mut_lvls]

        for lvl in mut_lvls[3:]:
            if '-domain' in lvl and 'Domains' not in var_fields:
                var_fields += ['Domains']
            else:
                var_fields += [lvl]

    elif isinstance(mut_lvls[0], tuple):
        var_fields = {'Gene', 'Canonical', 'Location', 'VarAllele'}
        cdata_lvls = list(mut_lvls)

        for lvl_list in mut_lvls:
            for lvl in lvl_list[2:]:
                if '-domain' in lvl and 'Domains' not in var_fields:
                    var_fields |= {'Domains'}
                else:
                    var_fields |= {lvl}

    else:
        raise TypeError(
            "Unrecognized <mut_lvls> argument: `{}`!".format(mut_lvls))

    # run the VEP command line wrapper to obtain a standardized
    # set of point mutation calls
    variants = process_variants(
        var_df, out_fields=var_fields, cache_dir=vep_cache_dir,
        temp_dir=out_path, assembly=data_dict['assembly'],
        distance=0, consequence_choose='pick', forks=4, update_cache=False
        )

    # remove mutation calls not assigned to a canonical transcript by VEP as
    # well as those not associated with genes linked to cancer processes
    variants = variants.loc[variants.CANONICAL == 'YES']
    if data_dict['copy'] is None:
        copies = pd.DataFrame(columns=['Gene', 'Copy'])
    else:
        copies = data_dict['copy']

    if use_genes:
        variants = variants.loc[variants.Gene.isin(use_genes)]
        copies = copies.loc[copies.Gene.isin(use_genes)]

    assert not variants.duplicated().any(), (
        "Variant data contains {} duplicate entries!".format(
            variants.duplicated().sum())
        )

    return BaseMutationCohort(data_dict['expr'], variants, cdata_lvls,
                              copies, data_dict['annot'], leaf_annot=None)


def load_cohort(cohort, expr_source, mut_lvls,
                vep_cache_dir, use_path=None, temp_path=None, use_genes=None):
    if use_path is not None and os.path.exists(use_path):
        try:
            with open(use_path, 'rb') as f:
                cdata = pickle.load(f)

        except:
            cdata = get_cohort_data(cohort, expr_source, mut_lvls,
                                    vep_cache_dir, temp_path, use_genes)

    else:
        cdata = get_cohort_data(cohort, expr_source, mut_lvls,
                                vep_cache_dir, temp_path, use_genes)

    if cohort != 'CCLE' and mut_lvls not in cdata.mtrees:
        cdata.merge(get_cohort_data(cohort, expr_source, mut_lvls,
                                    vep_cache_dir, temp_path, use_genes))

    return cdata


def get_cohort_subtypes(coh):
    if coh == 'METABRIC':
        metabric_samps = load_metabric_samps(metabric_dir)
        subt_dict = {subt: choose_metabric_subtypes(metabric_samps, subt)
                     for subt in ('LumA', 'luminal', 'nonbasal')}

    elif coh in tcga_subtypes:
        subt_dict = {
            subt: choose_tcga_subtypes(
                parse_tcga_subtypes("_{}".format(subt)), coh, subtype_file)
            for subt in tcga_subtypes[coh]
            }

    else:
        subt_dict = dict()

    return subt_dict

