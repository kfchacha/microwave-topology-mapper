import paramiko
import sqlite3
import re
import os

class RouterDB:
    def __init__(self):
        if os.path.exists("network_topology.db"):
            os.remove("network_topology.db")
            print("[i] Existing database removed. Starting fresh.")
        self.conn = sqlite3.connect("network_topology.db")
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS routers (
                chassis_mac TEXT PRIMARY KEY,
                router_type TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS interfaces (
                chassis_mac TEXT,
                interface_name TEXT,
                interface_mac TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS links (
                local_router_mac TEXT,
                local_port TEXT,
                neighbor_name TEXT,
                neighbor_mac TEXT,
                link_type TEXT
            )
        """)
        self.conn.commit()

    def insert_router_data(self, chassis_mac, router_type):
        chassis_mac = chassis_mac.strip().upper()
        self.conn.execute(
            "INSERT OR IGNORE INTO routers VALUES (?, ?)",
            (chassis_mac, router_type)
        )
        self.conn.commit()

    def insert_interface(self, chassis_mac, interface_name, interface_mac):
        if interface_mac:
            self.conn.execute(
                "INSERT OR IGNORE INTO interfaces VALUES (?, ?, ?)",
                (chassis_mac.strip().upper(), interface_name.strip(), interface_mac.strip().upper())
            )
            self.conn.commit()

    def insert_link(self, local_router_mac, local_port, neighbor_name, neighbor_mac, link_type):
        self.conn.execute(
            "INSERT INTO links VALUES (?, ?, ?, ?, ?)",
            (local_router_mac.strip().upper(), local_port.strip(), neighbor_name.strip(), neighbor_mac.strip().upper(), link_type)
        )
        self.conn.commit()

    def correlate_links(self):
        c = self.conn.cursor()
        links = c.execute("SELECT * FROM links").fetchall()
        routers = c.execute("SELECT * FROM routers").fetchall()
        interfaces = c.execute("SELECT * FROM interfaces").fetchall()

        chassis_map = {r[0].strip().upper(): r[1] for r in routers}  # chassis_mac -> router_type
        interface_map = {i[2].strip().upper(): i[0].strip().upper() for i in interfaces}  # interface_mac -> chassis_mac

        correlated = []
        for link in links:
            local_mac, local_port, nbr_name, nbr_mac, link_type = link
            local_mac = local_mac.strip().upper()
            nbr_mac = nbr_mac.strip().upper()
            remote_chassis = "UNKNOWN"

            if link_type == "fiber":
                if nbr_mac in chassis_map:
                    remote_chassis = nbr_mac
            elif link_type == "microwave":
                if nbr_mac in interface_map:
                    remote_chassis = interface_map[nbr_mac]

            correlated.append({
                "from": local_mac,
                "via": local_port,
                "to": remote_chassis,
                "type": link_type,
                "neighbor_mac": nbr_mac
            })

        print("\n[i] Interfaces loaded:", len(interface_map))
        print("[i] Links to correlate:", len(links))
        print("[i] Sample interface_map entries:", list(interface_map.items())[:5])
        return correlated


class RouterCollector:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ssh = None

    def connect(self):
        print(f"[+] Connecting to {self.ip}")
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.ip, username=self.username, password=self.password)
        print("[+] Connected")

    def run_command(self, cmd):
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return stdout.read().decode()

    def collect_interfaces(self, db):
        # Collect chassis info
        chassis_output = self.run_command("show platform chassis")
        chassis_mac_match = re.search(r"HW MAC address\s*:\s*([\w:]+)", chassis_output)
        router_type_match = re.search(r"Type\s*:\s*(.+)", chassis_output)
        chassis_mac = chassis_mac_match.group(1).strip() if chassis_mac_match else "UNKNOWN"
        router_type = router_type_match.group(1).strip() if router_type_match else "Unknown"
        db.insert_router_data(chassis_mac, router_type)
        print(f"[i] Collected chassis {chassis_mac}")

        # Collect all interfaces
        intf_output = self.run_command("show interface detail")
        for match in re.finditer(r"Interface:\s+(\S+).*?MAC address\s*:\s*([\w:]+)", intf_output, re.S):
            iface, mac = match.groups()
            db.insert_interface(chassis_mac, iface.strip(), mac.strip())

    def collect_links(self, db):
        # Collect chassis info again to know local MAC
        chassis_output = self.run_command("show platform chassis")
        chassis_mac_match = re.search(r"HW MAC address\s*:\s*([\w:]+)", chassis_output)
        chassis_mac = chassis_mac_match.group(1).strip() if chassis_mac_match else "UNKNOWN"

        # Collect LLDP neighbors
        lldp_output = self.run_command("show system lldp neighbor")
        neighbor_entries = re.findall(
            r"\|\s*(ethernet-\S+|mgmt0)\s*\|\s*([\w:]+)\s*\|\s*(\S+)\s*\|",
            lldp_output
        )
        for port, nbr_mac, nbr_name in neighbor_entries:
            link_type = "microwave" if nbr_mac.startswith(("00:11", "00:21")) else "fiber"
            db.insert_link(chassis_mac, port.strip(), nbr_name.strip(), nbr_mac.strip(), link_type)

        # Microwave ARP entries — replace dummy with real neighbor MAC
        mw_ports = [n for n in neighbor_entries if n[1].startswith(("00:11", "00:21"))]
        for port, _, _ in mw_ports:
            arp_output = self.run_command(f"show arpnd arp-entries interface {port}")
            for match in re.finditer(
                r"\|\s*(?:ethernet-\S+)\s*\|\s*\d+\s*\|\s*([\d\.]+)\s*\|\s*\w+\s*\|\s*([\w:]+)",
                arp_output
            ):
                ip, mac = match.groups()
                mac = mac.strip().upper()

                # Remove old dummy link
                db.conn.execute("""
                    DELETE FROM links
                    WHERE local_router_mac = ? AND local_port = ? AND link_type = 'microwave'
                """, (chassis_mac.strip().upper(), port.strip()))
                db.conn.commit()

                # Insert correct microwave link with real MAC
                db.insert_link(chassis_mac, port.strip(), ip.strip(), mac, "microwave")

    def disconnect(self):
        self.ssh.close()
        print("[+] Disconnected")


if __name__ == "__main__":
    router_ips = input("Enter router IPs (comma-separated): ").split(",")
    username = input("SSH Username: ").strip()
    password = input("SSH Password: ").strip()

    db = RouterDB()

    # 1️⃣ First pass: collect interfaces for all routers
    for ip in router_ips:
        collector = RouterCollector(ip.strip(), username, password)
        collector.connect()
        collector.collect_interfaces(db)
        collector.disconnect()

    # 2️⃣ Second pass: collect links / ARP
    for ip in router_ips:
        collector = RouterCollector(ip.strip(), username, password)
        collector.connect()
        collector.collect_links(db)
        collector.disconnect()

    correlated = db.correlate_links()
    print("\n[+] Correlated Network Links:")
    for link in correlated:
        print(f"{link['from']}:{link['via']} ({link['type'].upper()}) --> {link['to']} [MAC={link['neighbor_mac']}]")
