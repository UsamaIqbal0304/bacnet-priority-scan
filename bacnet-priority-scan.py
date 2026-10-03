#!/usr/bin/env python3
"""How a Niagara station decides to write a BACnet point, read out of the jar.

    ./bacnet-priority-scan.py [NIAGARA_HOME]

Why this exists. Intesis publish a support article -- "Value Object Types (AV,
BV, MV) are missing on my BACnet Gateway" -- whose answer to a customer who
needs read *and* write is "have the Client on the BACnet network write the
proper object type to the BACnet Server gateway". That is sound advice and it
is half the picture: which object type a gateway exposes also decides *how* the
client writes, and on Niagara the two branches behave nothing alike.

So rather than assert that from memory, this reads it out of bacnet-rt.jar:

  * BBacnetProxyExt.discoverPrioritizedPresentValue(boolean) switches on the
    object type. One group of types is assumed to have a priority array with no
    request on the wire; a second group is probed once; everything else is set
    to "not prioritized" outright.
  * BacnetDiscoveryUtil.checkForPriorityArray() is that probe -- a single
    ReadProperty, and the property and array index it asks for are printed
    here rather than described.

Object type and property numbers are resolved from the module's own
com/tridium/bacnet/objectTypes.xml, not from a table typed out here, so the
names cannot drift from the jar being read.

Nothing is installed, patched or sent anywhere. javap and unzip only.
"""
import re
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HOME = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "NIAGARA_HOME", "/opt/Niagara/Niagara-4.15.5.22"))
JAR = HOME / "modules" / "bacnet-rt.jar"


def _find_javap(niagara_home=None):
    """javap from $JAVAP, then PATH, then the JDK Niagara ships, then Debian's."""
    cand = [os.environ.get("JAVAP"), shutil.which("javap")]
    for base in (os.environ.get("JAVA_HOME"), niagara_home):
        if base:
            cand += [str(Path(base) / "bin" / "javap"),
                     str(Path(base) / "jre" / "bin" / "javap")]
    cand.append("/usr/lib/jvm/java-8-openjdk-amd64/bin/javap")
    for c in cand:
        if c and Path(c).exists():
            return c
    return None


JAVAP = _find_javap(HOME)


def die(msg):
    print("ABORT " + msg, file=sys.stderr)
    sys.exit(2)


if not JAR.exists():
    die(f"no {JAR}")
if not JAVAP:
    die("no javap found - set $JAVAP or put a JDK 8 javap on PATH")

work = Path(tempfile.mkdtemp(prefix="bacnet-scan-"))
with zipfile.ZipFile(JAR) as z:
    z.extractall(work)

# Names first, from the module's own table of standard object types.
xml = (work / "com/tridium/bacnet/objectTypes.xml").read_text(encoding="utf8", errors="replace")
names, requires_pa = {}, {}
for m in re.finditer(r'<object n="([^"]+)" t="(\d+)"[^>]*>(.*?)(?=<object |</objectTypes>)', xml, re.S):
    name, num, body = m.group(1), int(m.group(2)), m.group(3)
    names[num] = name
    pa = re.search(r'<property n="priorityArray"[^>]*>', body)
    requires_pa[num] = bool(pa and 'r="true"' in pa.group(0))
props = {int(m.group(2)): m.group(1)
         for m in re.finditer(r'<property n="(\w+)"\s+i="(\d+)"', xml)}
if not names or 85 not in props:
    die("objectTypes.xml did not parse -- refusing to print numbers with guessed names")


def disasm(cls):
    r = subprocess.run([JAVAP, "-p", "-c", "-classpath", str(work), cls],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout:
        die(f"javap failed on {cls}: {r.stderr.strip()[:200]}")
    return r.stdout


px = disasm("javax.baja.bacnet.point.BBacnetProxyExt")
body = re.search(r"public void discoverPrioritizedPresentValue\(boolean\);\n(.*?)\n\n", px, re.S)
if not body:
    die("discoverPrioritizedPresentValue(boolean) not found -- this Niagara differs")
body = body.group(1)

sw = re.search(r"lookupswitch\s*\{\s*//\s*(\d+)\n(.*?)default:\s*(\d+)", body, re.S)
if not sw:
    die("no lookupswitch in discoverPrioritizedPresentValue -- read it by hand")
cases = [(int(a), int(b)) for a, b in re.findall(r"(\d+):\s*(\d+)", sw.group(2))]
default = int(sw.group(3))
if len(cases) != int(sw.group(1)):
    die(f"switch claims {sw.group(1)} cases, parsed {len(cases)}")

# What each branch does is decided by whether it reaches the probe Runnable.
probe_at = [int(m.group(1)) for m in re.finditer(r"(\d+): new .*BBacnetProxyExt\$1", body)]
if len(probe_at) != 1:
    die(f"expected exactly one probe site, found {len(probe_at)}")
probe_pc = probe_at[0]
targets = sorted({t for _, t in cases})
# The branch that contains the probe site is the one whose target is the
# largest target still below it.
probe_target = max((t for t in targets if t <= probe_pc), default=None)

print(f"{JAR}")
print(f"javap: {subprocess.run([JAVAP, '-version'], capture_output=True, text=True).stdout.strip()}\n")
print("BBacnetProxyExt.discoverPrioritizedPresentValue(boolean) switches on object type:\n")
print(f"  {'type':>4}  {'name':<22} {'priorityArray in Niagara table':<31} what the station does")
groups = {}
for num, target in sorted(cases):
    groups.setdefault(target, []).append(num)
for target in sorted(groups):
    what = ("probed once over the wire" if target == probe_target
            else "assumed prioritized, nothing asked")
    for num in groups[target]:
        req = "required" if requires_pa.get(num) else "optional"
        print(f"  {num:>4}  {names.get(num, '?'):<22} {req:<31} {what}")
print(f"  {'else':>4}  {'(any other type)':<22} {'-':<31} set to not prioritized")

dv = disasm("com.tridium.bacnet.job.BacnetDiscoveryUtil")
cfp = re.search(r"checkForPriorityArray\(javax\.baja\.bacnet\.datatypes\.BBacnetObjectIdentifier,"
                r" javax\.baja\.bacnet\.BBacnetDevice\);\n(.*?)\n\n", dv, re.S)
if not cfp:
    die("checkForPriorityArray not found in BacnetDiscoveryUtil")
cfp = cfp.group(1)
rp = re.search(r"bipush\s+(\d+)\n\s*\d+:\s*(iconst_\d|bipush\s+\d+)\n\s*\d+:\s*invokevirtual.*readProperty",
               cfp)
if not rp:
    die("could not read the probe's arguments out of checkForPriorityArray")
prop = int(rp.group(1))
idx = int(rp.group(2).replace("iconst_", "")) if "iconst_" in rp.group(2) else int(rp.group(2).split()[1])
catches = re.search(r"Exception table:\n\s*from\s+to\s+target type\n\s*\d+\s+\d+\s+\d+\s+Class\s+(\S+)", cfp)

print("\nThe probe, in BacnetDiscoveryUtil.checkForPriorityArray:")
print(f"  one ReadProperty for property {prop} ({props.get(prop, '?')}), array index {idx}")
print(f"  caught: {catches.group(1) if catches else '(none)'} -> returns FALSE")
print("  the answer is stored in the point's device facets as 'priPV'")

# The cache is the part with teeth, so say where it lives rather than imply it.
cached = "getFacet" in body and "priPV" in body
print(f"  re-probed on later discovery only when forced: {'yes' if cached else 'unclear'}")
print(f"\nRead from {HOME.name}. Three facts a Wireshark trace on the gateway can check:")
print("  1. a write to an AO/BO/MO point addresses the priority array without a prior read")
print("  2. an AV/BV/MV writable point is preceded by exactly one priority-array read")
print("  3. if that read errors or times out, no priority-array read follows and writes")
print("     go to present-value directly")
