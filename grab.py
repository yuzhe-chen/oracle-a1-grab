"""Keeps asking Oracle Cloud for one Always Free Ampere A1 server (every free size, every availability domain)
until one is created, then records it in found.json. Prints only size / domain / result (the logs are public)."""
import json, os, sys, time
import oci

cfg = {"user": os.environ["OCI_USER"], "fingerprint": os.environ["OCI_FINGERPRINT"], "tenancy": os.environ["OCI_TENANCY"],
       "region": os.environ["OCI_REGION"], "key_content": os.environ["OCI_KEY"]}
T, NO_RETRY = cfg["tenancy"], oci.retry.NoneRetryStrategy()
compute = oci.core.ComputeClient(cfg)

def done(info):
    with open("found.json", "w") as f: json.dump(info, f, indent=1)
    print("CREATED", info["size"], info["ad"])
    sys.exit(0)

# never make a second server: stop if an A1 server already exists
live = [i for i in compute.list_instances(T, retry_strategy=NO_RETRY).data
        if i.shape == "VM.Standard.A1.Flex" and i.lifecycle_state not in ("TERMINATED", "TERMINATING")]
if live: done({"id": live[0].id, "size": "existing", "ad": live[0].availability_domain[-4:]})

ads = [a.name for a in oci.identity.IdentityClient(cfg).list_availability_domains(T, retry_strategy=NO_RETRY).data]
# smallest first: small slots free up far more often, and an A1 server can be resized up to 4/24 later
sizes = [(1, 6), (2, 12), (4, 24)]
deadline = time.time() + 290
slow = 0
while time.time() < deadline:
    for o, m in sizes:
        for ad in ads:
            if time.time() > deadline: break
            try:
                r = compute.launch_instance(oci.core.models.LaunchInstanceDetails(
                    availability_domain=ad, compartment_id=T, display_name="saxon", shape="VM.Standard.A1.Flex",
                    shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=o, memory_in_gbs=m),
                    source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=os.environ["IMAGE_ID"], boot_volume_size_in_gbs=100),
                    create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=os.environ["SUBNET_ID"], assign_public_ip=True),
                    metadata={"ssh_authorized_keys": os.environ["SSH_PUBKEY"]}), retry_strategy=NO_RETRY)
                done({"id": r.data.id, "size": f"{o}/{m}", "ad": ad[-4:]})
            except oci.exceptions.ServiceError as e:
                print(f"{o} OCPU/{m} GB {ad[-4:]}: {e.status} {e.code}", flush=True)
                # back off only when Oracle asks (429), longer each time in a row; otherwise keep a short gap
                if e.status == 429: slow = min(60, slow * 2 or 10); time.sleep(slow); continue
                slow = 0
            time.sleep(6)
print("no capacity this run")
