cd /mydata
git clone https://github.com/gjghfd/cfm.git
sudo apt-get install -y python3-pip
pip install psutil grpcio grpcio-tools
sudo mkdir -p /sys/fs/cgroup/memory/cfm
sudo chown -R gjghfd /sys/fs/cgroup/memory/cfm
cd cfm/protocol
source gen_protocol.sh
echo 65536 | sudo tee /proc/sys/net/core/somaxconn
cp /mydata/SoDM/service/build/generate_sampled_trace.py /mydata/cfm
cd /mydata/cfm
nohup python server.py --log &
sleep 1
# echo "Please source cfm/protocol/gen_protocol.sh first."
# for generating trace
# cd /mydata
# mkdir -p azure-data
# cd azure-data
# wget https://azurecloudpublicdataset2.blob.core.windows.net/azurepublicdatasetv2/azurefunctions_dataset2019/azurefunctions-dataset2019.tar.xz
# tar -xf azurefunctions-dataset2019.tar.xz
# pip install pandas
# cp /mydata/SoDM/service/build/generate_sampled_trace.py /mydata/cfm