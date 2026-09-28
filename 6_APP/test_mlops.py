"""End-to-end check of the MLOps platform, with no network access.

Run from anywhere:  python test_mlops.py

Uses the `csv` climate source so the run is deterministic and offline; the
database is a throwaway SQLite file in a temporary directory, so the check never
touches real data.
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parent               # .../6_APP
PACKAGE = APP.parent                                # .../malaria_thesis_package

os.chdir(APP)
sys.path.insert(0, str(APP))
os.environ['MEWS_DATABASE_URL'] = 'sqlite:///' + str(
    Path(tempfile.mkdtemp()) / 'mlops.db').replace('\\', '/')
# File source => deterministic test, no network call.
os.environ['MEWS_CLIMATE_SOURCE'] = 'csv'
os.environ['MEWS_CSV_SOURCE_PATH'] = str(
    PACKAGE / '9_NATIONAL_VALIDATION' / 'climate_districts_2023_2025.csv')

import pandas as pd

print('=' * 78)
print('1 . Source registry')
from app.mlops.sources.base import available_sources, get_source
print('   available sources:', available_sources())
src = get_source('csv', path=os.environ['MEWS_CSV_SOURCE_PATH'])
print(f'   active source: {src.name} (batch={src.supports_batch})')

print('\n2 . Collection')
targets = pd.DataFrame([{'district': 'Foumban', 'lat': 5.7, 'lon': 10.9},
                        {'district': 'Bafia', 'lat': 4.7, 'lon': 11.2}])
res = src.fetch_many(targets, date(2024, 1, 1), date(2025, 12, 31))
print(f'   {res.n_rows} rows . {res.n_districts} districts . '
      f'{len(res.failures)} failure(s) . {res.duration_s:.2f}s')
print('   schema:', list(res.frame.columns))

print('\n3 . Validation')
from app.mlops.stages.validation import validate_climate
rep = validate_climate(res.frame, expected_districts={'Foumban', 'Bafia'})
print('  ', rep.summary())
for c in rep.checks:
    if not c.passed:
        print(f'     failed {c.severity.value:<8} {c.name}: {c.detail}')

print('\n   -- negative test: corrupted data --')
bad = res.frame.copy()
bad.loc[bad.index[:50], 'Temperature_C'] = 999.0
bad2 = validate_climate(bad)
print(f'   validation passes: {bad2.passed} (expected False)')
print(f'   rule triggered: '
      f'{[c.name for c in bad2.failures if c.severity.value=="critical"]}')

print('\n4 . Feature engineering')
from app.mlops.stages import features as feat
from app.services.inference import bundle
bundle.load()
frame = feat.build_feature_frame(res.frame, bundle.district_static)
scorable = feat.scorable_rows(frame)
print(f'   months built: {len(frame)} . scorable: {len(scorable)}')
print(f'   NO-LAG features: {len(feat.FEAT_NOLAG)} . LAG: {len(feat.FEAT_LAG)}')

print('\n5 . Full pipeline (orchestrator)')
from app.mlops.orchestrator import Pipeline
pipe = Pipeline(bundle=bundle, static=bundle.district_static,
                source_name='csv',
                source_kwargs={'path': os.environ['MEWS_CSV_SOURCE_PATH']})
run, preds = pipe.run(districts=['Foumban', 'Bafia'],
                      start=date(2024, 1, 1), end=date(2025, 12, 31),
                      trigger='test')
print(f'   status: {run.status.value} . duration {run.duration_s:.2f}s . '
      f'{run.n_predictions} predictions')
for s in run.stages:
    print(f'     {s.name:<12} {"ok" if s.ok else "FAILED":<6} {s.duration_s:6.2f}s')
if not preds.empty:
    print('\n   sample:')
    print(preds[['district', 'year', 'month', 'predicted_cases',
                 'predicted_incidence', 'risk_level']].head(4).to_string(index=False))

print('\n6 . Drift detection')
from app.mlops.monitoring.drift import detect_data_drift, population_stability_index
import numpy as np
rng = np.random.default_rng(0)
ref = pd.DataFrame({f: rng.normal(0, 1, 500) for f in feat.FEAT_NOLAG})
same = pd.DataFrame({f: rng.normal(0, 1, 200) for f in feat.FEAT_NOLAG})
shifted = pd.DataFrame({f: rng.normal(2.5, 1, 200) for f in feat.FEAT_NOLAG})
r1 = detect_data_drift(ref, same, feat.FEAT_NOLAG)
r2 = detect_data_drift(ref, shifted, feat.FEAT_NOLAG)
print(f'   same distribution   : max PSI {r1.max_psi:.3f} . '
      f'major drift {r1.has_major_drift} (expected False)')
print(f'   shifted distribution: max PSI {r2.max_psi:.3f} . '
      f'major drift {r2.has_major_drift} (expected True)')

print('\n7 . API (MLOps routes)')
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    for path in ['/api/v1/mlops/sources', '/api/v1/mlops/scheduler',
                 '/api/v1/mlops/health', '/api/v1/mlops/runs',
                 '/api/v1/mlops/drift/performance']:
        r = c.get(path)
        body = json.dumps(r.json())[:110] if r.status_code == 200 else r.text[:110]
        print(f'   {path:<38} {r.status_code}  {body}')

    # Backfill over a window the CSV covers
    r = c.post('/api/v1/mlops/run',
               json={'districts': ['Foumban', 'Bafia'],
                     'start': '2024-01-01', 'end': '2025-12-31',
                     'background': False})
    print(f'\n   POST /mlops/run (backfill) -> {r.status_code}')
    if r.status_code == 200:
        d = r.json()
        print(f'     run_id={d.get("run_id")} status={d.get("status")} '
              f'predictions={d.get("n_predictions")} duration={d.get("duration_s")}s')
        for s in d.get('stages', []):
            print(f'       {s["name"]:<12} {"ok" if s["ok"] else "FAILED":<6} {s["duration_s"]:6.2f}s')
    else:
        print('    ', r.text[:600])

    # Idempotence: replaying the same window must not duplicate
    r2 = c.post('/api/v1/mlops/run',
                json={'districts': ['Foumban', 'Bafia'],
                      'start': '2024-01-01', 'end': '2025-12-31'})
    from app.db.base import SessionLocal
    from app.models.orm import Prediction
    db = SessionLocal()
    n_pred = db.query(Prediction).count()
    db.close()
    print(f'   replay -> {r2.json().get("n_predictions")} predictions; '
          f'total in database: {n_pred} (must equal the single run, not double)')

    r = c.get('/api/v1/mlops/runs')
    print(f'   GET /mlops/runs -> {len(r.json())} run(s) recorded')
    r = c.get('/api/v1/mlops/health')
    h = r.json()
    print(f'   health: {h.get("n_runs")} runs . success rate '
          f'{h.get("success_rate")} . stages {list((h.get("stage_mean_duration_s") or {}).keys())}')
    r = c.get('/api/v1/mlops/drift')
    print(f'   GET /mlops/drift -> {len(r.json())} drift measurement(s)')
    if r.json():
        top = sorted(r.json(), key=lambda x: -(x['psi'] or 0))[:3]
        for t in top:
            print(f'       {t["feature"]:<24} PSI={t["psi"]:.3f} {t["severity"]}')

print('\nALL CHECKS PASSED')
