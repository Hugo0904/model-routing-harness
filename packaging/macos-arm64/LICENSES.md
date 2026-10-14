# Fixed runtime notice snapshot

`license-snapshot/` contains only public license texts and `PYTHON.json` extracted
from the exact `astral-sh/python-build-standalone` release/archive pinned in
`runtime-lock.json`. It contains no interpreter binary, account state or cache.
`snapshot.json` records the original source archive hashes and every notice's
hash/size. Its own SHA-256 is pinned by the runtime lock.

Consumer builds verify these bytes, metadata/version/target, required notices,
and the exact extracted runtime binary before copying the notices. The original
full archive remains hash-verified as the provenance input. No license is omitted.
The one metadata alternative for zlib-ng was verified not redistributed: the
recorded pinned Python binary links Apple's system libz. Consumers compare that
exact binary hash; they do not need Xcode's otool to repeat a fixed fact.

This snapshot was generated from an already verified standalone bundle's notice
directory, cross-checked against that bundle's manifest, original fixed asset
hashes and `otool -L` of the exact pinned Python binary. Its upstream license
texts remain verbatim. Updating the runtime requires regenerating and reviewing
the snapshot, dependency proof and lock hash together. Do not refresh one alone.

This avoids an undeclared installation dependency: some macOS system tar builds
delegate `.tar.zst` decoding to a separate `zstd` executable. Maintainer extraction
can use that tool; installing MRH does not require it, Homebrew or a new SDK.
These notices do not declare a new license for MRH itself.
