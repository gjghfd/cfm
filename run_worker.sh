sudo kill -9 $(ps aux | grep "server.py" | awk '{print $2}') 
nohup python server.py --log &
sleep 1