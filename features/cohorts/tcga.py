
"""Consolidating datasets from The Cancer Genome Atlas for use in learning.

Authors: Michal Grzadkowski <grzadkow@ohsu.edu>

"""

import pandas as pd
from .mut import *

from ..expression import get_expr_firehose, get_expr_bmeg, get_expr_toil
from ..variants import get_variants_mc3, get_variants_firehose
from ..copies import get_copies_firehose

from ..annot import get_gencode
from ..utils import log_norm, match_tcga_samples


class MutationCohort(BaseMutationCohort):
    """An expression dataset used to predict genes' mutations (variants).

    Args:
        cohort (str): The label for a cohort of samples.
        mut_genes (:obj:`list` of :obj:`str`)
            Which genes' variants to include.
        mut_levels (:obj:`list` of :obj:`str`)
            What variant annotation levels to consider.
        expr_source (str): Where to load the expression data from.
        var_source (str): Where to load the variant data from.
        copy_source (:obj:`str`, optional)
            Where to load the copy number alteration data from. The default
            is to not use any CNA data.
        top_genes (:obj:`int`, optional)
            How many of the genes in the cohort ordered by descending
            mutation frequency to load mutation data for.
        cv_prop (float): Proportion of samples to use for cross-validation.
        cv_seed (int): The random seed to use for cross-validation sampling.

    Examples:
        >>> import synapseclient
        >>> syn = synapseclient.Synapse()
        >>> syn.login()
        >>>
        >>> cdata = MutationCohort(
        >>>     cohort='TCGA-BRCA', mut_genes=['TP53', 'PIK3CA'],
        >>>     mut_levels=['Gene', 'Form', 'Exon'], syn=syn
        >>>     )
        >>>
        >>> cdata2 = MutationCohort(
        >>>     cohort='TCGA-PAAD', mut_genes=['KRAS'],
        >>>     mut_levels=['Form_base', 'Exon', 'Location'],
        >>>     expr_source='Firehose', data_dir='../input-data/firehose',
        >>>     cv_seed=98, cv_prop=0.8, syn=syn
        >>>     )
        >>>
        >>> # load expression data with variant calls for the fifty most
        >>> # frequently mutated genes in the TCGA ovarian cohort
        >>> cdata3 = MutationCohort(cohort='TCGA-OV',
        >>>                         mut_genes=None, top_genes=50)
        >>>
        >>> # load expression data with variant calls for genes mutated in at
        >>> # least forty of the samples in the TCGA colon cohort
        >>> cdata3 = MutationCohort(cohort='TCGA-COAD',
        >>>                         mut_genes=None, samp_cutoff=40)

    """

    def __init__(self,
                 cohort, mut_genes, mut_levels=('Gene', 'Form'),
                 expr_source='BMEG', var_source='mc3', copy_source=None,
                 top_genes=100, samp_cutoff=None, cv_prop=2.0/3, cv_seed=None,
                 **coh_args):

        # loads gene expression data from the given source
        if expr_source == 'BMEG':
            expr_mat = get_expr_bmeg(cohort)
            expr = log_norm(expr_mat.fillna(0.0))

        elif expr_source == 'Firehose':
            expr_mat = get_expr_firehose(cohort, coh_args['expr_dir'])
            expr = log_norm(expr_mat.fillna(0.0))

        elif expr_source == 'toil':
            expr = get_expr_toil(cohort, coh_args['expr_dir'],
                                 coh_args['collapse_txs'])

        else:
            raise ValueError("Unrecognized source of expression data!")

        # loads gene variant data from the given source
        if var_source is None:
            var_source = expr_source

        if var_source == 'mc3':
            variants = get_variants_mc3(coh_args['syn'])

        elif var_source == 'Firehose':
            variants = get_variants_firehose(cohort, coh_args['var_dir'])

        else:
            raise ValueError("Unrecognized source of variant data!")

        # log-normalizes expression data, matches samples in the expression
        # data to those in the mutation data
        matched_samps = match_tcga_samples(expr.index, variants['Sample'])

        # loads copy number alteration data from the given source
        if copy_source == 'Firehose':
            copy_data = get_copies_firehose(cohort, coh_args['copy_dir'])

            # reshapes the matrix of CNA values into the same long format
            # mutation data is represented in
            copy_df = pd.DataFrame(copy_data.stack())
            copy_df = copy_df.reset_index(level=copy_df.index.names)
            copy_df.columns = ['Sample', 'Gene', 'Form']

            # removes CNA values corresponding to an absence of a variant
            copy_df = copy_df.loc[copy_df['Form'] != 0, :]

            # maps CNA integer values to their descriptions, appends
            # CNA data to the mutation data
            copy_df['Form'] = copy_df['Form'].map(
                {-2: 'HomDel', -1: 'HetDel', 1: 'HetGain', 2: 'HomGain'})
            variants = pd.concat([variants, copy_df])

        elif copy_source is not None:
            raise ValueError("Unrecognized source of CNA data!")

        # gets annotation data for each gene in the expression data, saves the
        # label of the cohort used as an attribute
        gene_annot = {at['gene_name']: {**{'Ens': ens}, **at}
                      for ens, at in get_gencode().items()
                      if at['gene_name'] in expr.columns}
        self.cohort = cohort

        super().__init__(expr, variants, matched_samps, gene_annot, mut_genes,
                         mut_levels, top_genes, samp_cutoff, cv_prop, cv_seed)


class TransferMutationCohort(BaseTransferMutationCohort):

    def __init__(self,
                 cohorts, mut_genes, mut_levels=('Gene', 'Form'),
                 expr_sources='BMEG', var_sources='mc3', copy_sources=None,
                 top_genes=250, samp_cutoff=None, cv_prop=2.0/3, cv_seed=None,
                 **coh_args):

        if isinstance(expr_sources, str):
            expr_sources = [expr_sources]

        if var_sources is None:
            var_sources = expr_sources

        if isinstance(var_sources, str):
            var_sources = [var_sources]

        if 'mc3' in var_sources:
            mc3_vars = get_variants_mc3(coh_args['syn'])
        else:
            mc3_vars = None

        if isinstance(copy_sources, str):
            copy_sources = [copy_sources]

        expr_dict = dict()
        for coh, expr_source in zip(cohorts, cycle(expr_sources)):
            if expr_source == 'BMEG':
                expr_mat = get_expr_bmeg(coh)
                expr_dict[coh] = log_norm(expr_mat.fillna(0.0))

            elif expr_source == 'Firehose':
                expr_mat = get_expr_firehose(coh, coh_args['expr_dir'])
                expr_dict[coh] = log_norm(expr_mat.fillna(0.0))

            elif expr_source == 'toil':
                expr_dict[coh] = get_expr_toil(coh, coh_args['expr_dir'],
                                               coh_args['collapse_txs'])

            else:
                raise ValueError("Unrecognized source of expression data!")

        var_dict = dict()
        for coh, var_source in zip(cohorts, cycle(var_sources)):

            if var_source == 'mc3':
                var_dict[coh] = mc3_vars.copy()

            elif var_source == 'Firehose':
                var_dict[coh] = get_variants_firehose(
                    coh, coh_args['var_dir'])

            else:
                raise ValueError("Unrecognized source of variant data!")

        matched_samps = {coh: match_tcga_samples(expr_dict[coh].index,
                                                 var_dict[coh]['Sample'])
                         for coh in cohorts}

        if copy_sources is not None:
            for coh, copy_source in zip(cohorts, cycle(copy_sources)):
                if copy_source == 'Firehose':
                    copy_data = get_copies_firehose(coh, coh_args['copy_dir'])

                    # reshapes the matrix of CNA values into the same long
                    # format mutation data is represented in
                    copy_df = pd.DataFrame(copy_data.stack())
                    copy_df = copy_df.reset_index(level=copy_df.index.names)
                    copy_df.columns = ['Sample', 'Gene', 'Form']
                    copy_df = copy_df.loc[copy_df['Form'] != 0, :]

                    # maps CNA integer values to their descriptions, appends
                    # CNA data to the mutation data
                    copy_df['Form'] = copy_df['Form'].map(
                        {-2: 'HomDel', -1: 'HetDel', 1: 'HetGain',
                         2: 'HomGain'})
                    var_dict[coh] = pd.concat([var_dict[coh], copy_df])

        annot_data = get_gencode()
        gene_annot = {coh: {at['gene_name']: {**{'Ens': ens}, **at}
                            for ens, at in annot_data.items()
                            if at['gene_name'] in expr_dict[coh].columns}
                      for coh in cohorts}
        self.cohorts = cohorts

        super().__init__(
            expr_dict, var_dict, matched_samps, gene_annot, mut_genes,
            mut_levels, top_genes, samp_cutoff, cv_prop, cv_seed
            )

