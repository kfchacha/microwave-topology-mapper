# 🛰️ Microwave & Fiber Network Topology Mapper

A Python-based tool for discovering and visualizing router connections across **fiber** and **microwave** links.  
The project includes:
- A **CLI version** for automated discovery and link correlation.
- A **Streamlit version** for interactive network visualization.

---

##  Features

-  SSH-based data collection using **Paramiko**
- 🧩 Local **SQLite3** database for storing topology data
-  Automatic correlation of **fiber** and **microwave** links
-  **Interactive topology visualization** (Streamlit + PyVis)
- ️ Real-time progress feedback and error handling

---

## 🧰 Tech Stack

| Component | Purpose |
|------------|----------|
| Python | Core logic |
| Paramiko | SSH automation |
| SQLite3 | Local storage |
| PyVis | Network graph rendering |
| Streamlit | Interactive UI |

---

## 📂 Repository Structure

microwave-topology-mapper/
│
├── cli_version/
│ └── microwave_mapper_cli.py # Command-line tool
│
├── streamlit_version/
│ └── app.py  # Interactive Streamlit app
│
├── assets/ # Diagrams or screenshots
├── requirements.txt
└── README.md

## ⚙️ Setup & Installation

```bash
git clone https://github.com/kfchacha/microwave-topology-mapper.git
cd microwave-topology-mapper
pip install -r requirements.txt



## CLI Usage
cd cli_version
python microwave_mapper_cli.py


Example workflow:

Enter router IPs (comma-separated).

Enter SSH username and password.

The script connects to routers, collects chassis, interface, and LLDP data.

Outputs correlated topology links to console and stores data in network_topology.db.

##  Streamlit Version
cd streamlit_version
streamlit run app.py


Features:

Enter router IPs and credentials from the sidebar.

Click Start Discovery to begin SSH collection.

Watch discovery progress live.

See a dynamic network topology map (fiber vs microwave color-coded).

---

 ## Future Enhancements

Auto-discovery using SNMP or API calls

Integrate NetBox or Grafana for topology storage

Export topology as JSON/GraphML

Dockerize the entire app for portability


##Note that this only works for Nokia Routers, the commands used only work for them, but this could be modified to use other vendors commands. 

---
## 🏽‍💻 Author

Kenyatta Peter Chacha
Network & DevOps Engineer
🇰🇪 Nairobi, Kenya
