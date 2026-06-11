# MTG Project Instructions

## Project Context
- This project is an MTG card search tool.
- The main entry point is `index.html`.
- Card data comes from the public Scryfall API.
- The page currently defaults to searching for `Lightning Bolt`.
- Search results should default to relevance-based ordering, with exact card-name matches ranked ahead of partial or card-face matches.

## Development Notes
- Prefer small, focused edits because this is currently a single-file web app.
- After UI or search behavior changes, check the local page at `file:///C:/Users/M/Desktop/mtg/index.html`.
- Keep user-facing text in Simplified Chinese unless there is a clear reason to use another language.
- Do not add secrets, API keys, tokens, passwords, or SSH private keys to this repository.

## Git And Repository
- The primary branch is `main`.
- The GitHub remote is `git@github.com:blueplaye/MTG.git`.
- For Codex cloud work, use the GitHub repository `blueplaye/MTG`.

## Files To Keep Out Of Git
- Do not commit Word documents or local drafts such as `*.docx`.
- Do not commit Office temporary lock files such as `~$*`.
- Do not commit dependency directories, build output, local caches, logs, or environment files.
- Current ignore rules are maintained in `.gitignore`.
