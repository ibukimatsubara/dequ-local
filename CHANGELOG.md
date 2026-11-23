# Changelog

All notable changes to DeQu are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).
How a release is made is described in [docs/releasing.md](docs/releasing.md).

## [Unreleased]

## [0.1.0] - 2026-11-23

License: DeQu Source-Available License, Change Date 2030-11-23

### Added

- Decision cards: an agent puts a card in the queue, a person answers it in the web app, and the answer goes back to the agent.
- Local server: SQLite storage with automatic deletion of old cards, an HTTP API and MCP tools.
- The web app, MCP clients and `dequ wait` can use the queue on the same computer without a token.
- The DeQu mark and exported icons.
- The DeQu Source-Available License permits workplace use and commercial product development, restricts paid redistribution and third-party hosting, and makes each version available under Apache-2.0 after four years.

### Changed

- Answering or withdrawing a card wakes only requests that are waiting for that card.

### Fixed

- Withdrawing an answered card now reports that it was already answered and preserves the choice, comment and history until expiry.
- Diagram icons use supplied images or initials. The API advertises only supplied images.
