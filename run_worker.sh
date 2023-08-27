sudo kill -9 $(ps aux | grep "server.py" | awk '{print $2}') 
cd protocol
source gen_protocol.sh
nohup python server.py --log &
sleep 1