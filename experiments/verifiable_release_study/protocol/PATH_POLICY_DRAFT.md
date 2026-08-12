# Portable Payload Path Policy

Version: `0.1.0-draft`  
Status: synthetic-pilot values; not frozen for registration

Every manifest path is interpreted as a logical POSIX-style path. The verifier
does not let host-platform path normalization define the policy.

## String rules

1. Decode the manifest as strict UTF-8 and require every path to equal its
   Unicode NFC normalization.
2. Require the literal prefix `payload/` and at least one component after it.
3. Permit `/` as the only separator. Reject backslash, NUL, ASCII control
   characters, Unicode format/control/surrogate code points, absolute paths,
   drive prefixes, empty components, `.` and `..` components.
4. Reject a path over 240 UTF-8 bytes or over 64 components.
5. Reject components ending in a space or period, containing `:`, or matching a
   Windows reserved device basename (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`,
   `LPT1`–`LPT9`) before any extension, case-insensitively.
6. Sort manifest entries by the UTF-8 bytes of their NFC path. Reject duplicate
   paths and Unicode `casefold()` collisions. This intentionally excludes some
   otherwise legal case-sensitive layouts to make the release portable.

## Filesystem rules

1. Resolve every logical path below a private release snapshot without following
   symbolic links.
2. Every listed payload must be a regular file with `st_nlink == 1`.
3. Reject symbolic links, hard links, sockets, FIFOs, devices, mount escapes, and
   any non-regular object before opening content.
4. Open with non-following semantics where the host provides them. Compare
   device, inode, mode, size, modification time, and link count before and after
   streaming. Any change returns `INPUT_CHANGED`.
5. The closed-world inventory is the set of all regular and non-regular entries
   below `payload/`, excluding directories themselves. Every observed entry must
   have exactly one manifest entry, and every manifest entry must exist.

## Compatibility

Symlink, hardlink, FIFO, inode, and non-following-open cases are compatible only
with environments that expose the required filesystem semantics. Compatibility
is frozen before registration and may not be changed after observing a verifier
decision.
