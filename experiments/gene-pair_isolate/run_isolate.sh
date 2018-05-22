#!/bin/bash

#SBATCH --job-name=pair-isolate
#SBATCH --partition=exacloud
#SBATCH --mem=1000
#SBATCH --time=500

#SBATCH --output=/home/exacloud/lustre1/CompBio/mgrzad/slurm/log-files/pair-isolate_%j.out
#SBATCH --error=/home/exacloud/lustre1/CompBio/mgrzad/slurm/log-files/pair-isolate_%j.err
#SBATCH --verbose


# move to working directory, load required packages and modules
cd /home/exacloud/lustre1/CompBio/mgrzad/bergamot
source activate precepts

# check for environment variables controlling the experiment, if these
# variables are not defined assign them default values
if [ -z ${cohort+x} ]
then
	echo "no cohort given, defaulting to TCGA-BRCA"
	export cohort="BRCA"
fi

if [ -z ${gene1+x} ]
then
	echo "no first gene given, defaulting to TP53"
	export gene1="TP53"
fi

if [ -z ${gene2+x} ]
then
	echo "no second gene given, defaulting to GATA3"
	export gene2="GATA3"
fi

if [[ "$gene2" < "$gene1" ]]
then
	dummy=$gene2
	export gene2=$gene1
	export gene1=$dummy
fi

if [ -z ${classif+x} ]
then
	echo "no classifier given, defaulting to Lasso"
	export classif="Lasso"
fi

if [ -z ${samp_cutoff+x} ]
then
	echo "no mimimum sample size cutoff given, defaulting to twenty"
	export samp_cutoff=25
fi

if [ -z ${mut_levels+x} ]
then
	echo "no mutation levels given, defaulting to Form_base+Exon"
	export mut_levels="Form_base__Exon"
fi

if [ -z ${test_max+x} ]
then
	echo "limiting maximum number of tests per node to fifty"
	export test_max=50
fi

# get the directory containing the experiment and the sub-directory where the
# subtypes enumareted during the setup step will be saved
export BASEDIR=HetMan/experiments/gene-pair_isolate
mkdir -p $BASEDIR/setup/${cohort}/${gene1}_${gene2}

# get the directory where the experiment results will be saved, removing it
# if it already exists
export OUTDIR=$BASEDIR/output/$cohort/${gene1}_${gene2}/$classif/samps_${samp_cutoff}/$mut_levels
rm -rf $OUTDIR
mkdir -p $OUTDIR/slurm

# setup the experiment by finding a list of mutation subtypes to be tested
if [ ! -e ${BASEDIR}/setup/${cohort}/${gene1}_${gene2}/mtypes_list__samps_${samp_cutoff}__levels_${mut_levels}.p ]
then

	srun -p=exacloud \
		--output=$BASEDIR/setup/slurm_${cohort}.txt \
		--error=$BASEDIR/setup/slurm_${cohort}.err \
		python $BASEDIR/setup_isolate.py -v \
		$cohort $gene1 $gene2 $mut_levels --samp_cutoff=$samp_cutoff
fi

# find how large of a batch array to submit based on how many mutation types were
# found in the setup enumeration
mtypes_count=$(cat ${BASEDIR}/setup/${cohort}/${gene1}_${gene2}/mtypes_count__samps_${samp_cutoff}__levels_${mut_levels}.txt)
export array_size=$(( $mtypes_count / $test_max ))

if [ $array_size -gt 299 ]
then
	export array_size=299
fi

# run the subtype tests in parallel
sbatch --array=0-$(( $array_size )) $BASEDIR/fit_isolate.sh

