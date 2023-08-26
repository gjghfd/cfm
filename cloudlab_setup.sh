## Please copy Manifest in Cloudlab to ./cloudlab.xml first

echo 'Please make sure you have configured every node in SoDM'

username='gjghfd'

# configure myself
bash init_cfm_env.sh

# generate hosts and ips
python genIPs.py
sed -i '1,4d' hosts.txt

while read -u10 line
do
    echo "Start configuring $line..."

    echo 'Upload env_setup.sh'
    scp init_cfm_env.sh "$username@$line:~/"

    echo "Set up environment in $line..."
    ssh -tt "$username@$line" "bash init_cfm_env.sh"

    echo "Everything done in $line!"
done 10< hosts.txt