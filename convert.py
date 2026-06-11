#!/usr/bin/env python3
"""
Convert Philips PAR/REC (T1 and DTI) data to BIDS format.

Usage:
    python convert.py <source_dir> <bids_output_dir>
    python convert.py <source_dir> <bids_output_dir> --update-json-only

Requires dcm2niix (system install) and nibabel/pandas (neuroim conda env).
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

LUT_PATH = Path(__file__).parent / 'subject_lut.tsv'
DWI_TEMPLATE_PATH = Path(__file__).parent / 'dwi_sidecar_template.json'

# Fields dcm2niix writes that are not BIDS-compliant or are misleading when the
# JSON is rebuilt from PAR rather than being dcm2niix's own output.
_DCM2NIIX_DROP = frozenset({
    'UsePhilipsFloatNotDisplayScaling',
    'ConversionSoftware',
    'ConversionSoftwareVersion',
    'ImageComments',  # may contain patient name (PHI)
})

# Handles all observed naming variants:
#   bluko_mrs_001_...  002_bluko_mrs_...  003_bluko_mrs_...  mrs_bluko_004_...
_SUBJECT_RE = re.compile(
    r'(?:^|_)(\d{3})_bluko'       # 002_bluko_mrs, 003_bluko_mrs
    r'|bluko_mrs_(\d{3})'         # bluko_mrs_001
    r'|mrs_bluko_(\d{3})',        # mrs_bluko_004
    re.IGNORECASE,
)


def extract_subject_id(stem: str) -> str | None:
    match = _SUBJECT_RE.search(stem)
    if match:
        return next(g for g in match.groups() if g is not None)
    return None


def get_scan_type(stem: str) -> str | None:
    s = stem.lower()
    if 'wipt1' in s or 't1_nfb' in s:
        return 't1'
    if 'wipq64' in s or 'q64wb' in s:
        return 'dwi'
    return None


def parse_par_metadata(par_file: Path) -> dict:
    """Extract patient name and scan date from PAR header."""
    meta = {'patient_name': '', 'scan_date': '', 'protocol': ''}
    with open(par_file, encoding='latin-1') as f:
        for line in f:
            if 'Patient name' in line and ':' in line:
                meta['patient_name'] = line.split(':', 1)[1].strip()
            elif 'Examination date/time' in line and ':' in line:
                meta['scan_date'] = line.split(':', 1)[1].strip().split('/')[0].strip()
            elif 'Protocol name' in line and ':' in line:
                meta['protocol'] = line.split(':', 1)[1].strip()
            if all(meta.values()):
                break
    return meta


def update_subject_lut(entries: list[dict]) -> None:
    """Merge new conversion entries into subject_lut.tsv, keyed on original_filename."""
    if LUT_PATH.exists():
        existing = pd.read_csv(LUT_PATH, sep='\t', dtype=str)
    else:
        existing = pd.DataFrame(columns=['subject_id', 'original_filename', 'scan_type',
                                         'patient_name', 'scan_date', 'protocol', 'converted_at'])

    new_df = pd.DataFrame(entries)
    merged = pd.concat([existing, new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=['original_filename', 'scan_type'], keep='last')
    merged = merged.sort_values(['subject_id', 'scan_type']).reset_index(drop=True)
    merged.to_csv(LUT_PATH, sep='\t', index=False)


def find_par_files(source_dir: Path) -> list[Path]:
    return sorted(p for p in source_dir.iterdir() if p.suffix.lower() == '.par')


def run_dcm2niix(par_file: Path, out_dir: Path) -> None:
    cmd = [
        'dcm2niix', '-b', 'y', '-z', 'y',
        '-f', '%p_%s',
        '-o', str(out_dir),
        str(par_file),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"dcm2niix failed:\n{result.stderr}")


def copy_bids_files(tmp: Path, sub_label: str, scan_type: str, dest_dir: Path) -> None:
    nii_files = sorted(tmp.glob('*.nii.gz'))
    if not nii_files:
        raise FileNotFoundError(f"dcm2niix produced no NIfTI output")

    # For DWI there should be one 4D volume; for T1 also one volume.
    # If multiple NIfTI files exist (e.g. separate b0 series), take the largest.
    nii = max(nii_files, key=lambda p: p.stat().st_size)
    stem = nii.name.replace('.nii.gz', '')

    if scan_type == 't1':
        suffixes = {f'{sub_label}_T1w.nii.gz': nii}
        json_src = tmp / f'{stem}.json'
        if json_src.exists():
            suffixes[f'{sub_label}_T1w.json'] = json_src
    else:
        suffixes = {f'{sub_label}_dwi.nii.gz': nii}
        for ext in ('.json', '.bvec', '.bval'):
            src = tmp / f'{stem}{ext}'
            bids_ext = ext.lstrip('.')
            if src.exists():
                suffixes[f'{sub_label}_dwi.{bids_ext}'] = src

    for dest_name, src in suffixes.items():
        shutil.copy2(src, dest_dir / dest_name)


def strip_dcm2niix_fields(json_path: Path) -> None:
    """Remove known non-BIDS/misleading fields from a dcm2niix-generated sidecar."""
    if not json_path.exists():
        return
    sidecar = json.loads(json_path.read_text())
    for key in _DCM2NIIX_DROP:
        sidecar.pop(key, None)
    json_path.write_text(json.dumps(sidecar, indent=2) + '\n')


def apply_dwi_template(json_path: Path) -> None:
    """Merge non-null fields from dwi_sidecar_template.json into an existing DWI sidecar."""
    if not DWI_TEMPLATE_PATH.exists():
        return
    template = json.loads(DWI_TEMPLATE_PATH.read_text())
    _meta_keys = {'_comment'}
    updates = {k: v for k, v in template.items() if k not in _meta_keys and not k.startswith('_') and v is not None}
    if not updates:
        return
    sidecar = json.loads(json_path.read_text()) if json_path.exists() else {}
    sidecar.update(updates)
    json_path.write_text(json.dumps(sidecar, indent=2) + '\n')


def parse_par_dwi_fields(par_file: Path) -> dict:
    """Extract per-subject DWI fields from PAR header and image table (PAR V4.2).

    Header:  AcquisitionNumber / SeriesNumber  ← 'Acquisition nr'
    Col 11:  PhilipsRescaleIntercept (RI)
    Col 12:  PhilipsRescaleSlope     (RS)
    Col 13:  PhilipsScaleSlope       (SS)
    Col 30:  EchoTime [ms → s]
    """
    fields = {}
    data_rows = []
    in_image_data = False

    with open(par_file, encoding='latin-1') as f:
        for line in f:
            stripped = line.strip()

            if 'Acquisition nr' in line and ':' in line:
                val = line.split(':', 1)[1].strip().split()[0]
                try:
                    acq = int(val)
                    fields['AcquisitionNumber'] = acq
                    fields['SeriesNumber'] = acq
                except ValueError:
                    pass

            elif 'IMAGE INFORMATION =' in stripped:
                in_image_data = True

            elif in_image_data and stripped and not stripped.startswith('#'):
                cols = stripped.split()
                if len(cols) > 30:
                    data_rows.append(cols)

    if not data_rows:
        return fields

    # Warn if rescaling or echo time vary unexpectedly across slices
    for col_idx, name in [(11, 'PhilipsRescaleIntercept'), (12, 'PhilipsRescaleSlope'),
                          (13, 'PhilipsScaleSlope'), (30, 'EchoTime')]:
        vals = {r[col_idx] for r in data_rows}
        if len(vals) > 1:
            print(f'  WARNING: {name} is not constant across slices in {par_file.name}: {vals}')

    first = data_rows[0]
    try:
        fields['PhilipsRescaleIntercept'] = float(first[11])
        fields['PhilipsRescaleSlope'] = float(first[12])
        fields['PhilipsScaleSlope'] = float(first[13])
        fields['EchoTime'] = round(float(first[30]) / 1000, 6)
    except (ValueError, IndexError):
        pass

    return fields


def apply_par_dwi_fields(json_path: Path, par_file: Path) -> None:
    """Merge PAR-extracted per-subject fields into an existing DWI sidecar."""
    fields = parse_par_dwi_fields(par_file)
    if not fields:
        return
    sidecar = json.loads(json_path.read_text()) if json_path.exists() else {}
    sidecar.update(fields)
    json_path.write_text(json.dumps(sidecar, indent=2) + '\n')


def convert_subject(sub_id: str, scan_type: str, par_file: Path, bids_root: Path,
                    update_json_only: bool = False) -> None:
    sub_label = f'sub-{sub_id}'
    modality = 'anat' if scan_type == 't1' else 'dwi'
    dest_dir = bids_root / sub_label / modality
    dest_dir.mkdir(parents=True, exist_ok=True)

    nii_path = dest_dir / f'{sub_label}_dwi.nii.gz' if scan_type == 'dwi' else dest_dir / f'{sub_label}_T1w.nii.gz'

    if update_json_only:
        if not nii_path.exists():
            raise FileNotFoundError(f'NIfTI not found, run full conversion first: {nii_path}')
        if scan_type == 'dwi':
            json_path = dest_dir / f'{sub_label}_dwi.json'
            json_path.write_text('{}\n')  # overwrite, don't merge into existing
            apply_dwi_template(json_path)
            apply_par_dwi_fields(json_path, par_file)
        return

    with tempfile.TemporaryDirectory() as tmp:
        run_dcm2niix(par_file, Path(tmp))
        copy_bids_files(Path(tmp), sub_label, scan_type, dest_dir)

    if scan_type == 'dwi':
        json_path = dest_dir / f'{sub_label}_dwi.json'
        strip_dcm2niix_fields(json_path)
        apply_dwi_template(json_path)
        apply_par_dwi_fields(json_path, par_file)


def write_dataset_description(bids_root: Path) -> None:
    desc = {
        'Name': 'cocaine_study',
        'BIDSVersion': '1.9.0',
        'DatasetType': 'raw',
        'GeneratedBy': [{'Name': 'dcm2niix', 'Version': 'v1.0.20240202'}],
    }
    (bids_root / 'dataset_description.json').write_text(json.dumps(desc, indent=2) + '\n')


def write_participants(bids_root: Path, subject_ids: list[str]) -> None:
    df = pd.DataFrame({'participant_id': [f'sub-{s}' for s in sorted(set(subject_ids))]})
    df.to_csv(bids_root / 'participants.tsv', sep='\t', index=False)


def validate_bids(bids_root: Path) -> bool:
    """Run bids-validator and print results. Returns True if no errors."""
    print('\nRunning BIDS validation...')
    result = subprocess.run(
        ['bids-validator', str(bids_root)],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    for line in output.splitlines():
        print(f'  {line}')
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description='Convert Philips PAR/REC to BIDS')
    parser.add_argument('source', type=Path, help='Directory containing PAR/REC files')
    parser.add_argument('output', type=Path, help='BIDS output directory')
    parser.add_argument('--skip-validate', action='store_true',
                        help='Skip BIDS validation after conversion')
    parser.add_argument('--update-json-only', action='store_true',
                        help='Only update DWI JSON sidecars from template; skip re-conversion '
                             '(NIfTI must already exist)')
    args = parser.parse_args()

    par_files = find_par_files(args.source)
    if not par_files:
        print(f'No PAR files found in {args.source}')
        return

    subject_ids: list[str] = []
    lut_entries: list[dict] = []
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    for par in par_files:
        sub_id = extract_subject_id(par.stem)
        scan_type = get_scan_type(par.stem)

        if sub_id is None:
            print(f'SKIP (no subject ID): {par.name}')
            continue
        if scan_type is None:
            print(f'SKIP (unknown scan type): {par.name}')
            continue

        action = 'Updating JSON' if args.update_json_only else 'Converting'
        print(f'{action} sub-{sub_id} [{scan_type}]: {par.name}')
        try:
            convert_subject(sub_id, scan_type, par, args.output,
                            update_json_only=args.update_json_only)
            subject_ids.append(sub_id)
            print(f'  -> {args.output}/sub-{sub_id}/{"anat" if scan_type == "t1" else "dwi"}/')

            if not args.update_json_only:
                meta = parse_par_metadata(par)
                lut_entries.append({
                    'subject_id': f'sub-{sub_id}',
                    'original_filename': par.name,
                    'scan_type': scan_type,
                    'patient_name': meta['patient_name'],
                    'scan_date': meta['scan_date'],
                    'protocol': meta['protocol'],
                    'converted_at': now,
                })
        except Exception as e:
            print(f'  ERROR: {e}')

    if subject_ids:
        if args.update_json_only:
            print(f'\nDone. DWI JSON sidecars updated from template.')
        else:
            write_dataset_description(args.output)
            write_participants(args.output, subject_ids)
            update_subject_lut(lut_entries)
            print(f'\nDone. BIDS dataset at {args.output}')
            print(f'Subject LUT updated: {LUT_PATH}')
            if not args.skip_validate:
                validate_bids(args.output)


if __name__ == '__main__':
    main()
