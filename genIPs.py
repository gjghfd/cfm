import xml.etree.ElementTree as ET

if __name__ == '__main__':
    tree = ET.parse('cloudlab.xml')
    hostsFile = open('hosts.txt', 'w')
    ipsFile = open('ips.txt', 'w')
    # pubipsFile = open('pubips.txt', 'w')
    rspec = tree.getroot()
    for node in rspec:
        if node.tag == '{http://www.geni.net/resources/rspec/3}node':
            hostsFile.write(node[6][0].attrib['hostname'] + '\n')
            ipsFile.write(node[2][0].attrib['address'] + '\n')
            # pubipsFile.write(node[5].attrib['ipv4'] + '\n')
