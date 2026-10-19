const recordsBody = document.querySelector("#records-body");
const recordsMessage = document.querySelector("#records-message");
const recordsCount = document.querySelector("#records-count");
const refreshButton = document.querySelector("#refresh-records");
const markerIdDocument = document.querySelector("#marker-id-document");

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function renderRecords(records, total) {
  recordsBody.replaceChildren();
  recordsCount.textContent = `${total} ${total === 1 ? "RECORD" : "RECORDS"}`;
  if (records.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "database-empty";
    cell.textContent = "No marker deliveries have been recorded yet. Show a supported marker to the camera to create the first record.";
    row.append(cell);
    recordsBody.append(row);
    recordsMessage.textContent = "Database connected.";
    return;
  }

  for (const record of records) {
    const row = document.createElement("tr");
    const values = [
      `ID ${record.marker_id}`,
      record.zone_name || "Unknown zone",
      record.center_x === null || record.center_y === null
        ? "Not available"
        : `X ${record.center_x} · Y ${record.center_y}`,
      record.status || "Unknown",
      formatTimestamp(record.detected_at),
      formatTimestamp(record.completed_at),
    ];
    for (const [index, value] of values.entries()) {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 0) cell.className = "database-marker-id";
      if (index === 3) {
        const statusClass = {
          blocked: "status-blocked",
          delivered: "status-delivered",
          moving: "status-moving",
          queued: "",
        }[record.status];
        cell.className = `database-status ${statusClass ?? ""}`;
      }
      row.append(cell);
    }
    recordsBody.append(row);
  }
  recordsMessage.textContent =
    `Showing ${records.length} of ${total} saved marker deliveries.`;
}

async function refreshRecords() {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/api/marker-records?limit=100", {
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Could not load saved marker records.");
    }
    renderRecords(result.records, result.total);
    await refreshMarkerIdDocument();
    if (result.persistence === "temporary") {
      recordsMessage.textContent =
        "This deployment is using temporary storage. Configure DATABASE_URL to retain marker history across requests.";
    }
  } catch (error) {
    recordsCount.textContent = "DATABASE UNAVAILABLE";
    recordsMessage.textContent = error.message;
    recordsBody.replaceChildren();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "database-empty";
    cell.textContent = "Records could not be loaded. Check the database connection and refresh.";
    row.append(cell);
    recordsBody.append(row);
  } finally {
    refreshButton.disabled = false;
  }
}

async function refreshMarkerIdDocument() {
  try {
    const response = await fetch("/api/marker-ids.txt", { cache: "no-store" });
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || "Could not load scanned marker IDs.");
    }
    markerIdDocument.textContent = await response.text();
  } catch (error) {
    markerIdDocument.textContent = `Scanned marker IDs could not be loaded: ${error.message}`;
  }
}

refreshButton.addEventListener("click", refreshRecords);
refreshRecords();
window.setInterval(refreshRecords, 5000);
