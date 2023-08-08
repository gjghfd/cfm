if [[ $# -ne 2 ]]; then
    echo "Parameter Error: need number of workers, load frac"
    exit 1
fi

servers="10.10.1.3:50051"

for i in $(seq 2 $1);
do
    servers=$servers",10.10.1."$((i+2))":50051"
done

python generate_sampled_trace.py --workload_config_path /mydata/cfm/workload.csv --load_frac $2
nohup python scheduler.py $servers > master.out 2>&1 &