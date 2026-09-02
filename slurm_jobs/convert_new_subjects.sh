#!/bin/bash -l
#SBATCH --job-name=convert_bids
#SBATCH --partition=standard
#SBATCH --qos=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=%x_%j.log

set -eo pipefail

module load miniforge3
CONDA_BASE="${CONDA_EXE%/bin/conda}"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate neuroim

SOURCE_DIR=~/scratch_new_subjects
OUTPUT_DIR=/shares/hare.econ.uzh/data-cocaine-habits/bids_dataset

cd ~/repos/dti_bids_conversion
python -u convert.py "$SOURCE_DIR" "$OUTPUT_DIR" --skip-validate
