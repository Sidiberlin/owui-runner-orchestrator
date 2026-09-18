# Admission control counts committed memory, not /proc/meminfo

Inside an LXC (and behind cgroup limits generally), /proc/meminfo is virtualized and can report a fraction of the real host memory. A protection gate reading it inverted into a denial-of-service: it refused spawns while the host had gigabytes free. The budget instead accounts deterministically for the memory the orchestrator has promised to runners, which is knowable exactly. The live probe remains available as opt-in and both numbers are shown in /_orch/status.
