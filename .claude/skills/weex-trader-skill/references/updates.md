# Release Notes

This note is for repository maintainers. It is not part of the normal runtime routing for the skill.

## Packaging

1. Update the skill contents you want to publish from this checkout.
2. Use the packaging workflow that exists in your local Codex environment or release tooling.
3. Pass repo-relative or user-provided paths into that workflow instead of hardcoding a workstation-specific absolute path.

## Versioning

- Keep version information in git tags, release notes, or external package metadata.
- Do not assume `SKILL.md` carries an inline version key; the current frontmatter only defines the skill name and description.
