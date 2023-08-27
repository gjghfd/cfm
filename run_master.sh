if [[ $# -lt 2 ]]; then
    echo "Parameter Error: need: number of workers, load frac, [tot_far (GiB)]"
    exit 1
fi

servers="10.10.1.5:50061"

for i in $(seq 2 $1);
do
    servers=$servers",10.10.1."$((i+4))":50061"
done

python generate_sampled_trace.py --workload_config_path /mydata/cfm/workload.csv --load_frac $2

if [[ $# -eq 2 ]]; then
    echo "Copy the command and run."
    echo "nohup python scheduler.py $servers > master.out 2>&1 &"
else
    echo "Total Far Memory = "$3"GiB"
    tot_far=$3
    max_far=$((tot_far*1024))
    echo "Copy the command and run."
    echo "nohup python scheduler.py $servers --max_far $max_far > master.out 2>&1 &"
fi