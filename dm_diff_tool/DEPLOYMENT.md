# Deployment

The Matter Data Model Diff Checker is a static site — no server-side build or runtime is needed. The same procedure works for every target (local, S3, GitHub Pages, any other static host).

## Single procedure

1. Regenerate the manifest whenever `data_model/` changes:

   ```bash
   cd dm_diff_tool
   python3 generate_manifest.py
   ```

   This writes `data_manifest.json` listing every version and XML file. It's committed to the repo, so local dev is zero-setup.

2. Upload or serve the `dm_diff_tool/` directory as-is. The front-end fetches `data_manifest.json` to discover versions; nothing else is required.

## GitHub Pages

Automated via `.github/workflows/deploy-tools.yml` on every push to `main`. To enable it on a fork, open the repository settings and set **Pages → Source** to **GitHub Actions**. The workflow runs `generate_manifest.py` and uploads the result.

## S3

1. If `data_model/` has changed since the committed `data_manifest.json` was generated, run `python3 generate_manifest.py` first.
2. Upload `dm_diff_tool/` to a bucket with public read (`s3:GetObject`).
