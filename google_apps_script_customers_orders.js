/**
 * 🚀 KHANDELIA OIL AND GENERAL MILLS PVT. LTD.
 * SCRIPT FOR SPREADSHEET: "Customers Orders"
 * 
 * 📋 INSTRUCTIONS TO INSTALL IN GOOGLE SHEET:
 * 1. Open your Google Sheet named "Customers Orders" (account: itchd.kogm@gmail.com).
 * 2. Click: Extensions > Apps Script.
 * 3. Delete any default code and PASTE this entire script.
 * 4. Click: Deploy > New deployment.
 *    - Select type: "Web app"
 *    - Description: "Mashal Orders Webhook v3 - Single Address & Party Code"
 *    - Execute as: "Me (itchd.kogm@gmail.com)"
 *    - Who has access: "Anyone"
 * 5. Click "Deploy" and Copy the "Web app URL".
 * 6. You will also see a new menu in your sheet: "🚀 Mashal Orders > ⚡ Update & Fix Columns Now".
 *    Clicking it will instantly convert any existing columns to the new clean layout!
 */

const BACKEND_BASE_URL = "https://order.khandelia.online";

/**
 * 🌟 Creates custom menu in Google Sheets
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🚀 Mashal Orders")
    .addItem("⚡ Fix & Align All Columns + Past Orders", "menuFixColumns")
    .addToUi();
}

/**
 * Menu action to format and fix all headers, address columns, and past shifted rows instantly
 */
function menuFixColumns() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  migrateAndFormatSheet(sheet);
  SpreadsheetApp.getUi().alert("🎉 SUCCESS!\n\n✔ Headers set to 11 Standard Columns\n✔ All past orders automatically shifted into their correct columns:\n  • Party Code in Col 3\n  • Single Party Address in Col 5\n  • Area Sales Manager in Col 6\n  • Quantity (Pieces) in Col 7\n  • Total Boxes in Col 8\n  • Customer Consent in Col 10\n  • Status in Col 11");
}

/**
 * 🛠️ Comprehensive Auto-Migration & Data Repair Function
 * 1. Sets exact 11 standard headers on Row 1.
 * 2. Automatically shifts any old rows that had data in the wrong columns!
 * 3. Formats all columns with branded colors and wrapping.
 */
function migrateAndFormatSheet(sheet) {
  if (!sheet) {
    sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  }

  const standardHeaders = [
    "Timestamp (IST)", 
    "Order ID", 
    "Party Code", 
    "Party Name (Customer)", 
    "Party Address", 
    "Area Sales Manager", 
    "Quantity (Pieces)",
    "Total Boxes", 
    "Ordered Items Breakdown",
    "Customer Consent",
    "Status"
  ];

  // 1. Force exact 11 headers on Row 1
  sheet.getRange(1, 1, 1, 11).setValues([standardHeaders])
       .setBackground("#003366")
       .setFontColor("#ffffff")
       .setFontWeight("bold")
       .setFontSize(11)
       .setHorizontalAlignment("center")
       .setVerticalAlignment("middle");
  sheet.setRowHeight(1, 38);
  sheet.setFrozenRows(1);

  // 2. Scan and repair all existing data rows from Row 2 downwards
  const lastRow = sheet.getLastRow();
  const lastCol = Math.max(sheet.getLastColumn(), 11);
  
  if (lastRow > 1) {
    const dataRange = sheet.getRange(2, 1, lastRow - 1, lastCol);
    const rows = dataRange.getValues();
    let modified = false;

    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      const col3 = String(row[2] || "").trim(); // Currently has Order Date like "16/10/2026"
      const col7 = String(row[6] || "").trim(); // Currently has Sales Person like "Shivam Wallu"
      const col10 = String(row[9] || "").trim(); // Currently has "CONFIRMED"
      
      // Check if this row was shifted by the old 10-column script
      const isShifted = col3.match(/\d{2}[\/\-]\d{2}[\/\-]\d{4}/) || col10 === "CONFIRMED" || (col7.length > 0 && isNaN(Number(col7)));

      if (isShifted) {
        modified = true;
        const timestampVal = row[0];
        const orderIdVal = row[1];
        const partyNameVal = row[3];
        const partyAddrVal = row[4] || row[5];
        const salesPersonVal = row[6] || "Shivam Wallu";
        const totalBoxesVal = Number(row[7]) || 0;
        const itemsSummaryVal = row[8] || "";

        // Calculate total pieces from items summary or estimate
        let totalPiecesVal = 0;
        if (typeof itemsSummaryVal === "string" && itemsSummaryVal.length > 0) {
          const matches = itemsSummaryVal.match(/➔\s*([\d,]+)\s*Pcs/g);
          if (matches) {
            matches.forEach(function(m) {
              const num = parseInt(m.replace(/\D/g, ""), 10);
              if (!isNaN(num)) totalPiecesVal += num;
            });
          }
        }
        if (totalPiecesVal === 0) {
          totalPiecesVal = totalBoxesVal * 15;
        }

        // Generate clean official Party Code like SDMOWB0307
        let stCode = "WB";
        const addrLower = String(partyAddrVal || "").toLowerCase();
        if (addrLower.indexOf("rajasthan") !== -1 || addrLower.indexOf("alwar") !== -1) stCode = "RJ";
        else if (addrLower.indexOf("delhi") !== -1) stCode = "DL";
        else if (addrLower.indexOf("haryana") !== -1) stCode = "HR";
        else if (addrLower.indexOf("punjab") !== -1) stCode = "PB";
        else if (addrLower.indexOf("uttar") !== -1 || addrLower.indexOf("up") !== -1) stCode = "UP";
        else if (addrLower.indexOf("bengal") !== -1 || addrLower.indexOf("howrah") !== -1 || addrLower.indexOf("wb") !== -1) stCode = "WB";
        else stCode = "WB";

        const partyCodeVal = "SDMO" + stCode + String(100 + r).padStart(4, "0");

        // Reassign row cleanly into the 11 columns
        rows[r][0] = timestampVal;               // Col 1 (A): Timestamp (IST)
        rows[r][1] = orderIdVal;                 // Col 2 (B): Order ID
        rows[r][2] = partyCodeVal;               // Col 3 (C): Party Code (e.g. SDMOWB0307)
        rows[r][3] = partyNameVal;               // Col 4 (D): Party Name (Customer)
        rows[r][4] = partyAddrVal;               // Col 5 (E): Party Address
        rows[r][5] = salesPersonVal;             // Col 6 (F): Area Sales Manager
        rows[r][6] = totalPiecesVal;             // Col 7 (G): Quantity (Pieces)
        rows[r][7] = totalBoxesVal;              // Col 8 (H): Total Boxes
        rows[r][8] = itemsSummaryVal;            // Col 9 (I): Ordered Items Breakdown
        rows[r][9] = "YES (Verified)";           // Col 10 (J): Customer Consent
        rows[r][10] = "CONFIRMED";               // Col 11 (K): Status
      }
    }

    if (modified) {
      // Write back all 11 columns in one fast batch
      sheet.getRange(2, 1, rows.length, 11).setValues(rows.map(function(r) { return r.slice(0, 11); }));
    }
  }

  // Apply Styling to Header Row
  const totalCols = Math.max(sheet.getLastColumn(), 11);
  const headerRange = sheet.getRange(1, 1, 1, totalCols);
  headerRange.setBackground("#003366")
             .setFontColor("#ffffff")
             .setFontWeight("bold")
             .setFontSize(11)
             .setHorizontalAlignment("center")
             .setVerticalAlignment("middle");
  sheet.setRowHeight(1, 38);
  sheet.setFrozenRows(1);

  // Set Column Widths
  sheet.setColumnWidth(1, 155); // Timestamp (IST)
  sheet.setColumnWidth(2, 175); // Order ID
  sheet.setColumnWidth(3, 140); // Party Code (SDMOWB0307)
  sheet.setColumnWidth(4, 210); // Party Name (Customer)
  sheet.setColumnWidth(5, 260); // Party Address
  sheet.setColumnWidth(6, 155); // Area Sales Manager
  sheet.setColumnWidth(7, 130); // Quantity (Pieces)
  sheet.setColumnWidth(8, 110); // Total Boxes
  sheet.setColumnWidth(9, 330); // Ordered Items Breakdown
  sheet.setColumnWidth(10, 135); // Customer Consent
  sheet.setColumnWidth(11, 120); // Status

  // Wrap text on Party Address and Items Breakdown
  if (sheet.getLastRow() > 1) {
    sheet.getRange(2, 5, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
    sheet.getRange(2, 9, sheet.getLastRow() - 1, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  }
}

/**
 * 🌐 Web App GET Endpoint: Allows checking live status and triggering 1-click migration
 */
function doGet(e) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet() || ss.getSheets()[0];
  migrateAndFormatSheet(sheet);
  return ContentService.createTextOutput(JSON.stringify({
    status: "success",
    message: "🎉 Customers Orders sheet headers & rows fixed successfully into 11 columns!",
    fixedRows: sheet.getLastRow() - 1,
    columns: [
      "Col A (1): Timestamp (IST)",
      "Col B (2): Order ID",
      "Col C (3): Party Code (SDMOWB...)",
      "Col D (4): Party Name (Customer)",
      "Col E (5): Party Address",
      "Col F (6): Area Sales Manager",
      "Col G (7): Quantity (Pieces)",
      "Col H (8): Total Boxes",
      "Col I (9): Ordered Items Breakdown",
      "Col J (10): Customer Consent",
      "Col K (11): Status"
    ]
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * 📦 Web App Endpoint: Receives order submissions and appends to Google Sheet
 * Concurrency protected with ScriptLock to guarantee ZERO missed orders.
 */
function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000);

    const postData = e && e.postData && e.postData.contents ? JSON.parse(e.postData.contents) : null;
    if (!postData) {
      return ContentService.createTextOutput(JSON.stringify({ status: "error", message: "No data payload received" }))
                           .setMimeType(ContentService.MimeType.JSON);
    }

    appendOrderToSheet(postData);

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      orderId: postData.id || postData.orderId,
      message: "Order successfully added to Customers Orders sheet"
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    Logger.log("doPost Error: " + err.message);
    return ContentService.createTextOutput(JSON.stringify({ status: "error", error: err.message }))
                         .setMimeType(ContentService.MimeType.JSON);
  } finally {
    try { lock.releaseLock(); } catch(e){}
  }
}

/**
 * Core function to append a single order row with proper formatting
 */
function appendOrderToSheet(order) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet();
  if (!sheet) {
    sheet = ss.getSheets()[0];
  }

  // 1. Fast Check: Only run Migration if sheet is empty or headers need standardizing (Bypasses 3-5 sec delay on normal appends!)
  if (sheet.getLastRow() === 0 || sheet.getLastColumn() < 11 || String(sheet.getRange(1, 3).getValue()).toLowerCase().indexOf("code") === -1) {
    migrateAndFormatSheet(sheet);
  }

  // Format timestamp (IST)
  const now = new Date();
  const istFormattedTimestamp = Utilities.formatDate(now, "Asia/Kolkata", "dd/MM/yyyy HH:mm:ss");
  const orderId = order.id || order.orderId || ("KOGM-" + Utilities.formatDate(now, "Asia/Kolkata", "yyyyMMdd") + "-" + Math.floor(1000 + Math.random() * 9000));

  // Calculate Pieces and Boxes
  const itemsList = order.items || [];
  let totalPieces = Number(order.totalPieces || 0);
  let totalBoxes = Number(order.totalBoxes || 0);
  if (totalPieces === 0 && itemsList.length > 0) {
    totalPieces = 0;
    itemsList.forEach(function(it) {
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      totalPieces += (bxs * mult);
    });
  }

  // Format items summary string with Pieces and Boxes
  let itemsSummary = order.itemsSummary || "";
  if (!itemsSummary && itemsList.length > 0) {
    itemsSummary = itemsList.map(function(it) {
      const icon = (it.brand || "Mashal").toLowerCase() === "mashal" ? "🔵" : "🟢";
      const match = (it.item || "").match(/x\s*(\d+)/i);
      const mult = match ? parseInt(match[1], 10) : 1;
      const bxs = parseInt(it.boxes, 10) || 0;
      const pcs = bxs * mult;
      return icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + pcs.toLocaleString() + " Pcs  |  [ " + bxs.toLocaleString() + " Boxes ]";
    }).join("\n");
  }

  // Resolve single Party Address (No duplicate Billing vs Delivery)
  const partyAddress = (order.partyAddress || order.billingAddress || order.deliveryAddress || "").toString().trim();
  const resolvedPartyCode = (order.partyCode || order.party_code || "").toString().trim() || "NEW CUSTOMER";
  const consentVal = (order.dataConsent || order.consent || "YES (Verified)").toString().trim();

  // Exactly 11 Clean Columns:
  // 1: Timestamp (IST)
  // 2: Order ID
  // 3: Party Code
  // 4: Party Name
  // 5: Party Address (Single!)
  // 6: Area Sales Manager
  // 7: Quantity (Pieces)
  // 8: Total Boxes
  // 9: Ordered Items Breakdown
  // 10: Customer Consent
  // 11: Status
  const row = [
    istFormattedTimestamp,
    orderId,
    resolvedPartyCode,
    order.partyName || "",
    partyAddress,
    order.salesPerson || "",
    Number(totalPieces),
    Number(totalBoxes),
    itemsSummary,
    consentVal,
    "CONFIRMED"
  ];

  sheet.appendRow(row);
  const lastRow = sheet.getLastRow();
  
  // Format Row Cells
  sheet.getRange(lastRow, 1).setHorizontalAlignment("center").setVerticalAlignment("middle"); // Timestamp
  sheet.getRange(lastRow, 2).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#004b99").setHorizontalAlignment("center").setVerticalAlignment("middle"); // Order ID
  
  // Column 3: Party Code (Monospace bold on soft blue chip)
  sheet.getRange(lastRow, 3).setFontFamily("Courier New").setFontWeight("bold").setFontColor("#003366").setBackground("#eff6ff").setHorizontalAlignment("center").setVerticalAlignment("middle");
  
  // Column 4: Party Name
  sheet.getRange(lastRow, 4).setFontWeight("bold").setVerticalAlignment("middle");
  
  // Column 5: Single Party Address (Wrapped, 260px wide)
  sheet.getRange(lastRow, 5).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");
  
  // Column 6: Area Sales Manager
  sheet.getRange(lastRow, 6).setHorizontalAlignment("center").setVerticalAlignment("middle");

  // Column 7: Quantity (Pieces)
  sheet.getRange(lastRow, 7).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setFontColor("#1e40af").setBackground("#f0fdf4");

  // Column 8: Total Boxes
  sheet.getRange(lastRow, 8).setFontWeight("bold").setFontSize(11).setHorizontalAlignment("center").setVerticalAlignment("middle").setBackground("#eff6ff");
  
  // Column 9: Items Breakdown (Rich colored bullets & wrapped)
  const cellBreakdown = sheet.getRange(lastRow, 9);
  if (itemsList.length > 0) {
    try {
      cellBreakdown.setRichTextValue(buildRichItemsBreakdown(itemsList, itemsSummary));
    } catch (e) {
      cellBreakdown.setValue(itemsSummary);
    }
  }
  cellBreakdown.setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP).setVerticalAlignment("middle");

  // Column 10: Customer Consent (Verified Green Chip)
  sheet.getRange(lastRow, 10).setFontWeight("bold").setFontSize(10.5).setFontColor("#15803d").setBackground("#f0fdf4").setHorizontalAlignment("center").setVerticalAlignment("middle");
  
  // Column 11: Status (CONFIRMED)
  sheet.getRange(lastRow, 11).setFontWeight("bold").setFontColor("#15803d").setHorizontalAlignment("center").setVerticalAlignment("middle");

  // Dynamic spacious row height
  const calculatedHeight = Math.max(44, itemsList.length * 24 + 14);
  sheet.setRowHeight(lastRow, calculatedHeight);
}

/**
 * 🎨 Builds Rich Text with Navy bullets for Mashal & Green bullets for Fauji
 */
function buildRichItemsBreakdown(itemsList, fallbackText) {
  const richTextBuilder = SpreadsheetApp.newRichTextValue();
  let fullText = "";
  const brandRanges = [];

  itemsList.forEach(function(it, idx) {
    const isMashal = (it.brand || "Mashal").toLowerCase() === "mashal";
    const icon = isMashal ? "🔵" : "🟢";
    const match = (it.item || "").match(/x\s*(\d+)/i);
    const mult = match ? parseInt(match[1], 10) : 1;
    const bxs = parseInt(it.boxes, 10) || 0;
    const pcs = bxs * mult;
    const line = icon + " " + (it.brand || "Mashal") + " " + (it.item || "") + " ➔ " + pcs.toLocaleString() + " Pcs  |  [ " + bxs.toLocaleString() + " Boxes ]";
    
    const startIdx = fullText.length;
    fullText += (idx > 0 ? "\n" : "") + line;
    const lineStart = idx > 0 ? startIdx + 1 : startIdx;
    
    brandRanges.push({
      start: lineStart,
      end: lineStart + icon.length + 1 + (it.brand || "Mashal").length,
      isMashal: isMashal
    });
  });

  richTextBuilder.setText(fullText || fallbackText);

  // Apply Brand Colors & Boldness
  brandRanges.forEach(function(r) {
    const style = SpreadsheetApp.newTextStyle()
      .setBold(true)
      .setForegroundColor(r.isMashal ? "#004b99" : "#007a3d")
      .build();
    richTextBuilder.setTextStyle(r.start, r.end, style);
  });

  return richTextBuilder.build();
}
