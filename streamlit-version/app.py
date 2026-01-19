import streamlit as st
import sqlite3
import paramiko
import re
import os
import tempfile
from pyvis.network import Network

# -------------------------------
# Core database and SSH classes
# -------------------------------
class RouterDB:
    def __init__(self):
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

    def clear(self):
        self.conn.execute("DELETE FROM routers")
        self.conn.execute("DELETE FROM interfaces")
        self.conn.execute("DELETE FROM links")
        self.conn.commit()

    def insert_router_data(self, chassis_mac, router_type):
        self.conn.execute("INSERT OR IGNORE INTO routers VALUES (?, ?)", (chassis_mac, router_type))
        self.conn.commit()

    def insert_interface(self, chassis_mac, interface_name, interface_mac):
        self.conn.execute("INSERT OR IGNORE INTO interfaces VALUES (?, ?, ?)",
                          (chassis_mac, interface_name, interface_mac))
        self.conn.commit()

    def insert_link(self, local_router_mac, local_port, neighbor_name, neighbor_mac, link_type):
        self.conn.execute("INSERT INTO links VALUES (?, ?, ?, ?, ?)",
                          (local_router_mac, local_port, neighbor_name, neighbor_mac, link_type))
        self.conn.commit()

    def correlate_links(self):
        """Return all links without collapsing duplicates — so multiple physical connections remain visible."""
        c = self.conn.cursor()
        links = c.execute("SELECT * FROM links").fetchall()
        interfaces = c.execute("SELECT * FROM interfaces").fetchall()
        interface_map = {i[2].strip().upper(): i[0].strip().upper() for i in interfaces}

        correlated = []
        for local_mac, local_port, nbr_name, nbr_mac, link_type in links:
            nbr_mac = nbr_mac.strip().upper()
            remote_chassis = interface_map.get(nbr_mac, "UNKNOWN")
            correlated.append({
                "from": local_mac,
                "via": local_port,
                "to": remote_chassis,
                "type": link_type,
                "neighbor_mac": nbr_mac
            })
        return correlated


class RouterCollector:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.ssh = None

    def connect(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(self.ip, username=self.username, password=self.password, timeout=10)
        self.ssh = ssh

    def run_command(self, cmd):
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        return stdout.read().decode()

    def collect_all(self, db: RouterDB):
        chassis_output = self.run_command("show platform chassis")
        chassis_mac = re.search(r"HW MAC address\s*:\s*([\w:]+)", chassis_output)
        router_type = re.search(r"Type\s*:\s*(.+)", chassis_output)
        chassis_mac = chassis_mac.group(1).strip().upper() if chassis_mac else "UNKNOWN"
        router_type = router_type.group(1).strip() if router_type else "Unknown"
        db.insert_router_data(chassis_mac, router_type)

        # Interfaces
        intf_output = self.run_command("show interface detail")
        for match in re.finditer(r"Interface:\s+(\S+).*?MAC address\s*:\s*([\w:]+)", intf_output, re.S):
            iface, mac = match.groups()
            db.insert_interface(chassis_mac, iface.strip(), mac.strip().upper())

        # LLDP (Fiber)
        lldp_output = self.run_command("show system lldp neighbor")
        neighbor_entries = re.findall(r"\|\s*(ethernet-\S+|mgmt0)\s*\|\s*([\w:]+)\s*\|\s*(\S+)\s*\|", lldp_output)
        for port, nbr_mac, nbr_name in neighbor_entries:
            link_type = "microwave" if nbr_mac.startswith(("00:11", "00:21")) else "fiber"
            db.insert_link(chassis_mac, port.strip(), nbr_name.strip(), nbr_mac.strip().upper(), link_type)

        # ARP (Microwave)
        for port, nbr_mac, _ in neighbor_entries:
            if nbr_mac.startswith(("00:11", "00:21")):
                arp_output = self.run_command(f"show arpnd arp-entries interface {port}")
                for match in re.finditer(r"\|\s*(?:ethernet-\S+)\s*\|\s*\d+\s*\|\s*([\d\.]+)\s*\|\s*\w+\s*\|\s*([\w:]+)", arp_output):
                    ip, mac = match.groups()
                    db.insert_link(chassis_mac, port.strip(), ip.strip(), mac.strip().upper(), "microwave")

    def disconnect(self):
        if self.ssh:
            self.ssh.close()


# -------------------------------
# Streamlit UI
# -------------------------------
st.set_page_config(page_title="Network Topology Discovery", layout="wide")
st.title(" Network Topology Discovery & Visualization")

# Inputs
st.sidebar.header("Discovery Settings")
router_input = st.sidebar.text_area("Router IPs (comma-separated)", "172.17.0.6,172.17.0.7,172.17.0.8")
username = st.sidebar.text_input("SSH Username", "admin")
password = st.sidebar.text_input("SSH Password", type="password")

if st.sidebar.button("Start Discovery"):
    db = RouterDB()
    db.clear()
    ips = [i.strip() for i in router_input.split(",") if i.strip()]

    st.write(f"Starting discovery for {len(ips)} routers...")
    progress = st.progress(0)
    for idx, ip in enumerate(ips, start=1):
        try:
            collector = RouterCollector(ip, username, password)
            collector.connect()
            collector.collect_all(db)
            collector.disconnect()
            st.success(f"✅ Collected data from {ip}")
        except Exception as e:
            st.error(f"❌ Failed to collect from {ip}: {e}")
        progress.progress(idx / len(ips))

    st.success(" Discovery Complete. Correlating links...")
    correlated = db.correlate_links()

    # -------------------------------
    # Build Network Visualization
    # -------------------------------
    net = Network(height="700px", width="100%", bgcolor="#1e1e1e", font_color="white", directed=False)
    net.barnes_hut()
    routers = db.conn.execute("SELECT * FROM routers").fetchall()
    router_icon_url = "https://icons.veryicon.com/png/o/miscellaneous/open-ncloud/router-14.png"

    # Add nodes
    for chassis_mac, router_type in routers:
        net.add_node(
            chassis_mac.strip().upper(),
            label=f"{router_type}\n{chassis_mac}",
            shape="image",
            image=router_icon_url,
            size=40,
            title=f"{router_type} ({chassis_mac})"
        )

    # -------------------------------
    # Enhanced Edge Drawing Logic
    # -------------------------------
    # Group by (from, to) pair to detect fiber + microwave coexistence
    link_groups = {}
    for link in correlated:
        from_node = link["from"].strip().upper()
        to_node = link["to"].strip().upper()
        link_type = link["type"].lower()
        nbr_mac = link["neighbor_mac"].strip().upper()

        if "mgmt" in link["via"].lower():
            continue

        # Fiber links connect to neighbor chassis MAC
        if link_type == "fiber":
            to_node = nbr_mac

        if to_node == "UNKNOWN":
            continue

        key = tuple(sorted([from_node, to_node]))
        if key not in link_groups:
            link_groups[key] = set()
        link_groups[key].add(link_type)

    # Draw the links
    edge_counter = 0
    for (from_node, to_node), types in link_groups.items():
        edge_counter += 1

        # Style based on link types
        if {"fiber", "microwave"}.issubset(types):
            color = "#800080"  # purple
            width = 5
            dashes = [10, 5]
            label = "Fiber + Microwave"
        elif "fiber" in types:
            color = "#00FF00"
            width = 4
            dashes = False
            label = "Fiber"
        elif "microwave" in types:
            color = "#FFA500"
            width = 3
            dashes = [5, 5]
            label = "Microwave"
        else:
            color = "#CCCCCC"
            width = 2
            dashes = [2, 2]
            label = "Unknown"

        smooth = {
            "enabled": True,
            "type": "curvedCCW" if "fiber" in types else "curvedCW",
            "roundness": 0.25
        }

        net.add_edge(
            from_node,
            to_node,
            id=f"{from_node}-{to_node}-{edge_counter}",
            color=color,
            width=width,
            dashes=dashes,
            title=label,
            smooth=smooth
        )

    # Render in Streamlit
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as tmpfile:
        net.save_graph(tmpfile.name)
        st.components.v1.html(open(tmpfile.name, "r", encoding="utf-8").read(), height=750, scrolling=True)
        os.remove(tmpfile.name)

else:
    st.info(" Enter your router IPs and credentials in the sidebar, then click **Start Discovery**.")
