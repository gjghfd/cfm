echo "This script is used to restart remote workers"
echo "Make sure that you have copy Manifest to cloudlab.xml"
python genIPs.py
sed -i '1,4d' hosts.txt
username='gjghfd'
while read -u10 line
do
    ssh -tt "$username@$line" "cd /mydata/cfm && git pull origin master && bash run_worker.sh"
    echo "Worker restarted in $line!"
done 10< hosts.txt