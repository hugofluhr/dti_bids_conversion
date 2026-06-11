# DTI BIDS Conversion

Converts Philips PAR/REC MRI data (T1 and DTI) to [BIDS](https://bids.neuroimaging.io/) format for the cocaine habits study.

## Data

Each subject has two scans exported from the Philips scanner as PAR/REC pairs:

| Scan | Protocol | BIDS output |
|---|---|---|
| T1 structural | `WIP T1_NFB` | `sub-{id}/anat/sub-{id}_T1w.nii.gz` |
| Diffusion (DTI) | `WIP q64 wb` | `sub-{id}/dwi/sub-{id}_dwi.nii.gz` |

The DTI protocol acquires 1 b=0 volume + 64 directions at b=1000 s/mm².

## Dependencies

- **dcm2niix** (system): `brew install dcm2niix`
- **Python packages** (neuroim conda env): `conda env create -f environment.yml`

## Usage

```bash
conda run -n neuroim python convert.py <source_dir> <bids_output_dir>
```

Example:
```bash
conda run -n neuroim python convert.py \
  /path/to/data/cocaine_study/DTI \
  /path/to/data/cocaine_study/ds-cocaine-habits
```

The script will:
1. Detect all PAR files in `source_dir` and classify them as T1 or DWI
2. Run `dcm2niix` on each file to produce NIfTI + bvec/bval
3. Write `dataset_description.json` and `participants.tsv` into the BIDS root
4. For DWI, build the JSON sidecar: keep dcm2niix-extracted fields (e.g. `ImageOrientationPatientDICOM`), strip non-BIDS fields, then apply static fields from `dwi_sidecar_template.json` and per-subject fields (EchoTime, AcquisitionNumber, SeriesNumber, Philips rescaling factors) extracted from the PAR file
5. Update `subject_lut.tsv` (gitignored) with subject metadata and conversion timestamp
6. Run `bids-validator` on the output (pass `--skip-validate` to bypass)

To update only the DWI JSON sidecars (e.g. after editing `dwi_sidecar_template.json`) without re-running dcm2niix:

```bash
conda run -n neuroim python convert.py <source_dir> <bids_output_dir> --update-json-only
```

## DWI sidecar template

`dwi_sidecar_template.json` holds static protocol-level fields shared across all subjects (e.g. `PhaseEncodingDirection`, `TotalReadoutTime`, scanner metadata). Edit this file to update protocol-level metadata. Per-subject fields are always extracted automatically from the PAR file.

## Subject LUT

`subject_lut.tsv` (gitignored) is updated on every full conversion run and maps original PAR filenames to BIDS subject IDs, along with patient name, scan date, and protocol. Useful for tracking provenance.

## BIDS output structure

```
ds-cocaine-habits/
├── dataset_description.json
├── participants.tsv
├── sub-001/
│   ├── anat/
│   │   ├── sub-001_T1w.nii.gz
│   │   └── sub-001_T1w.json
│   └── dwi/
│       ├── sub-001_dwi.nii.gz
│       ├── sub-001_dwi.bval
│       ├── sub-001_dwi.bvec
│       └── sub-001_dwi.json
├── sub-002/
...
```
