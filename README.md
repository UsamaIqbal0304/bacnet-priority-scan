# bacnet-priority-scan

How a Niagara station decides to write a BACnet point - whether it writes
through the priority array or straight to present-value - read out of
`bacnet-rt.jar` rather than out of the documentation.

One Python file, standard library only.

```
./bacnet-priority-scan.py [NIAGARA_HOME]
```

## Why this exists

Gateway vendors are regularly asked for Value objects (AV, BV, MV) instead of
Output objects, and the usual answer is that the client should write the proper
object type. That is sound advice and it is half the picture: the object type a
gateway exposes also decides **how** Niagara writes to it, and the two branches
do not behave alike.

Three object types are assumed to have a priority array and are written without
anything being asked on the wire. Seven are probed once with a single
ReadProperty, and if that probe errors or times out the point is marked not
prioritized and writes go to present-value for the life of that configuration.
Everything else is marked not prioritized outright. The answer is cached in the
point's device facets, and it is only re-probed on a later discovery if the
discovery is forced.

So a gateway whose AV responds slowly the first time it is discovered gets a
point that writes to present-value, and nothing in the point says that is what
happened.

## What it reads, and where from

- `BBacnetProxyExt.discoverPrioritizedPresentValue(boolean)` - the switch on
  object type, and which group each type falls into.
- `BacnetDiscoveryUtil.checkForPriorityArray()` - the probe itself: the
  property number and array index it asks for, which exception it catches, what
  it returns on failure, and the facet the answer is stored in.
- The module's own `com/tridium/bacnet/objectTypes.xml` for object type and
  property names, so they cannot drift from the jar being read.

## Read first: what it does and does not touch

**It never speaks BACnet and never opens a socket.** It unzips
`modules/bacnet-rt.jar` and runs `javap`. Nothing is installed, patched,
written to a station or sent anywhere.

It needs a Niagara installation to read and a `javap` from a JDK 8. It looks
for `javap` in `$JAVAP`, then on `PATH`, then under `$JAVA_HOME` and the
Niagara install, then in Debian's default location. The install to read comes
from the first argument or `$NIAGARA_HOME`.

**The output below was measured against Niagara 4.15.5.22.** Another version
may differ, and that is the point - rerun it against yours rather than
trusting this page. The last three lines are checks a Wireshark trace on the
gateway settles in an afternoon.

## Running it

```
$ ./bacnet-priority-scan.py
/opt/Niagara/Niagara-4.15.5.22/modules/bacnet-rt.jar
javap: 1.8.0_504

BBacnetProxyExt.discoverPrioritizedPresentValue(boolean) switches on object type:

  type  name                   priorityArray in Niagara table  what the station does
     1  AnalogOutput           required                        assumed prioritized, nothing asked
     4  BinaryOutput           required                        assumed prioritized, nothing asked
    14  MultiStateOutput       required                        assumed prioritized, nothing asked
     2  AnalogValue            optional                        probed once over the wire
     5  BinaryValue            optional                        probed once over the wire
    19  MultiStateValue        optional                        probed once over the wire
    40  CharacterStringValue   optional                        probed once over the wire
    45  IntegerValue           optional                        probed once over the wire
    46  LargeAnalogValue       optional                        probed once over the wire
    48  PositiveIntegerValue   required                        probed once over the wire
  else  (any other type)       -                               set to not prioritized

The probe, in BacnetDiscoveryUtil.checkForPriorityArray:
  one ReadProperty for property 87 (priorityArray), array index 0
  caught: java/lang/Exception -> returns FALSE
  the answer is stored in the point's device facets as 'priPV'
  re-probed on later discovery only when forced: yes

Read from Niagara-4.15.5.22. Three facts a Wireshark trace on the gateway can check:
  1. a write to an AO/BO/MO point addresses the priority array without a prior read
  2. an AV/BV/MV writable point is preceded by exactly one priority-array read
  3. if that read errors or times out, no priority-array read follows and writes
     go to present-value directly
```

## The same finding, written up

The output above, which object types are written through the priority array, which are probed once, and what a failed probe does to the point, is also a page: <https://plantroomlabs.com/tools/bacnet-priority-scan/>. It carries this run, the download with its size and SHA-256, and the note explaining the reasoning.

## Licence

MIT. Written by Usama Iqbal at [Plantroom Labs](https://plantroomlabs.com).
