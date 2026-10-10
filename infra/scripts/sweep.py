#!/usr/bin/env python3
"""List anything that could cost money, in every AWS region. Read-only.

    python infra/scripts/sweep.py

It only calls "describe" and "list" operations: nothing is created, changed
or deleted. Checked in every enabled region: EC2 instances, EBS volumes, EBS
snapshots owned by the account, Elastic IPs, NAT gateways, load balancers and
RDS instances. Account-wide: S3 buckets. No identifiers of people or secrets
are involved; resource ids, types and states are printed.
"""

from __future__ import annotations

import json
import sys

from common import aws, fail, require_tools

CHECKS = [
    # label, CLI arguments, JMESPath query giving one short line per resource
    ("EC2 instances", ["ec2", "describe-instances"],
     "Reservations[].Instances[?State.Name!='terminated'][].join(' ', [InstanceId, InstanceType, State.Name])"),
    ("EBS volumes", ["ec2", "describe-volumes"],
     "Volumes[].join(' ', [VolumeId, to_string(Size), 'GiB', State])"),
    ("EBS snapshots", ["ec2", "describe-snapshots", "--owner-ids", "self"],
     "Snapshots[].join(' ', [SnapshotId, to_string(VolumeSize), 'GiB'])"),
    ("Elastic IPs", ["ec2", "describe-addresses"],
     "Addresses[].join(' ', [PublicIp, AssociationId || 'NOT ATTACHED'])"),
    ("NAT gateways", ["ec2", "describe-nat-gateways"],
     "NatGateways[?State!='deleted'].join(' ', [NatGatewayId, State])"),
    ("Load balancers", ["elbv2", "describe-load-balancers"],
     "LoadBalancers[].join(' ', [LoadBalancerName, Type])"),
    ("RDS instances", ["rds", "describe-db-instances"],
     "DBInstances[].join(' ', [DBInstanceIdentifier, DBInstanceClass, DBInstanceStatus])"),
]


def main() -> int:
    require_tools("aws")
    identity = aws("sts", "get-caller-identity", check=False)
    if identity.returncode != 0:
        fail("the AWS CLI has no working credentials")
    print(f"Account {json.loads(identity.stdout)['Account']}, read-only sweep\n")

    regions = json.loads(
        aws("ec2", "describe-regions", "--query", "Regions[].RegionName", region="us-east-1").stdout
    )
    found = 0
    for region in sorted(regions):
        lines = []
        for label, command, query in CHECKS:
            result = aws(*command, "--query", query, region=region, check=False)
            if result.returncode != 0:
                lines.append(f"    {label}: could not be read ({result.stderr.strip()[:80]})")
                continue
            for item in json.loads(result.stdout or "[]"):
                lines.append(f"    {label}: {item}")
                found += 1
        print(f"{region}: " + ("nothing" if not lines else ""))
        for line in lines:
            print(line)

    buckets = aws("s3api", "list-buckets", "--query", "Buckets[].Name", check=False)
    names = json.loads(buckets.stdout or "[]") if buckets.returncode == 0 else []
    print(f"\nS3 buckets (all regions): {', '.join(names) if names else 'none'}")
    print(f"\n{found} billable resource(s) found in {len(regions)} regions, {len(names or [])} bucket(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
