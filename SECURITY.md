# Security Policy

## Supported Versions

Only the latest stable release receives security fixes.

| Version | Supported |
|---------|-----------|
| 1.x     | ✅ Yes    |
| < 1.0   | ❌ No     |

---

## Reporting a Vulnerability

**Do not open a public GitHub Issue for security vulnerabilities.**

Report vulnerabilities privately by opening a [GitHub Security Advisory](https://github.com/Tanwydd/phantomime/security/advisories/new), or by emailing the maintainer directly (address on the GitHub profile).

Please include:

- A clear description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix if you have one

You will receive an acknowledgement within 72 hours. If the report is confirmed, a fix will be prioritised and a patched release will be published. You will be credited in the `CHANGELOG.md` unless you prefer to remain anonymous.

---

## Scope

Security issues relevant to this project include:

- Vulnerabilities in Phantomime's own code (e.g. unsafe use of `eval`, path traversal, unsafe deserialization)
- Dependencies with known CVEs that affect Phantomime users (`playwright`, `numpy`, `curl-cffi`)
- Fingerprint leaks that could expose users operating under a privacy requirement

Out of scope:

- Vulnerabilities in websites targeted by users of this library
- Anti-bot bypass techniques as a security concern — that is the library's core purpose
- Issues in the user's own code that happens to use Phantomime

---

## Dependency Security

Phantomime keeps its dependency surface minimal by design. If you discover a CVE in a direct dependency, please report it here so we can pin or upgrade accordingly.
