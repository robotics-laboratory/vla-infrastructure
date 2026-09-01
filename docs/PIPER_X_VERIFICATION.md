# PIPER_X_VERIFICATION.md

## Goal

Resolve a real PIPER-X embodiment contract and prove that Isaac/MuJoCo mappings preserve intended robot semantics.

## Static/driver evidence [[gate:A]]

Pin:

```text
LeRobot revision
PIPER-X LeRobot plugin/package
AgileX driver revision
robot model variant
exact command API/control mode
action features
observation features
joint order
joint units/representation
gripper semantics
model source
```

Generic Piper is not accepted as PIPER-X without evidence.

## Hardware runtime contract [[gate:R0]] / [[gate:R1]]

For each arm resolve independently:

```text
CAN/device identity
actual firmware
driver profile
robot model
command API
command mode
sign semantics revision
```

Firmware alone is not a complete command contract. Do not transfer a workaround from a different driver/API path without evidence.

## Executable embodiment parity

For the authoritative reference, Isaac and MuJoCo test:

```text
home/zero pose
joint lower/upper limits
positive perturbation J1..J6
gripper endpoints
sampled q vectors
FK/TCP
```

Resolve tolerances from evidence:

```text
max position error
max orientation error
zero tolerance
joint-limit tolerance
```

Do not invent numeric tolerances in the specification.

## Sign test

For each joint:

```text
q_home -> q_home + small positive delta on one joint
```

verify intended positive direction and TCP response.

## Model asset

Pin immutable repository/revision/path/hash or equivalent immutable artifact.

"Official repository" alone is not sufficient acceptance evidence.

## Calibration

Calibration is a first-class artifact:

```text
revision
artifact id/hash
frame convention
date/source evidence
```

Changed calibration invalidates dependent evidence as defined by the gate graph.
