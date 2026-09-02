#!/bin/bash -l
#SBATCH --job-name=bids_validate
#SBATCH --partition=standard
#SBATCH --qos=normal
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=%x_%j.log

set -eo pipefail

module load miniforge3
CONDA_BASE="${CONDA_EXE%/bin/conda}"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate neuroim

bids-validator /shares/hare.econ.uzh/data-cocaine-habits/bids_dataset
