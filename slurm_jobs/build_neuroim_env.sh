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
conda env remove -n neuroim -y 2>/dev/null || true
conda env create -f environment.yml
conda activate neuroim

# The real bids-validator CLI is npm-distributed (conda-forge's package of
# the same name is a different, unrelated Python library -- see
# environment.yml comment). npm's global prefix defaults to the active
# conda env when the nodejs conda package is active, so this installs the
# `bids-validator` executable into $CONDA_PREFIX/bin.
npm install -g bids-validator@1.15.0

echo "Done. neuroim env created."
which bids-validator
