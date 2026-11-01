# Contributing

Bug reports, accessibility improvements and reproducibility fixes are welcome. For a new analysis period or methodology change, open an issue describing the question, proposed comparison and source coverage first.

1. Fork the repository and create a branch.
2. Follow the README setup and run `python -m unittest discover -s tests -v`.
3. For report changes, serve it locally and check desktop/mobile layouts, keyboard controls and both color themes. Run `node --check cta-bus-speed-scorecard.js`.
4. For analysis changes, explain the expected metric impact, test a small synthetic case and document thresholds or exclusions. Do not replace the published snapshot without documenting its source manifest and analysis period.
5. Open a pull request with the problem, change and validation results.

Keep raw downloads, databases, environment files, personal filesystem paths and private data out of commits. Tests use synthetic inputs and must not require credentials or network access. New code is contributed under MIT; preserve third-party source notices and applicable data terms.

Be respectful and constructive. Do not post personal information or security vulnerabilities in public issues; use the security policy for private reports.
