#!/bin/bash -l
#SBATCH --job-name=build_neuroim_env
#SBATCH --partition=standard
#SBATCH --qos=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=%x_%j.log

# Rebuild the 'neuroim' conda env from environment.yml.
# No GPU needed -- conda-forge package installs only (dcm2niix, pandas,
# nibabel, pybids, bids-validator). See sciencecluster skill: env builds
# don't need --gres even for CUDA stacks, let alone plain CPU packages.
#
# #!/bin/bash -l (login shell) is required here so `module load` works --
# see ~/.zshrc: conda is now provided via the cluster's admin-maintained
# `module load miniforge3`, not a home-directory install.

set -eo pipefail

module load miniforge3
CONDA_BASE="${CONDA_EXE%/bin/conda}"
source "$CONDA_BASE/etc/profile.d/conda.sh"

cd ~/repos/dti_bids_conversion
conda env create -f environment.yml
echo "Done. neuroim env created."
