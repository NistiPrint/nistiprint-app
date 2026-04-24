function showTab(tabName) {
  const tabs = document.querySelectorAll('.tab-content')
  const tabElements = document.querySelectorAll('.tab')

  tabs.forEach(tab => {
    tab.style.display = 'none' // Hide all tab contents
  })

  tabElements.forEach(tab => {
    tab.classList.remove('active') // Remove active class from all tabs
  })

  document.getElementById(tabName).style.display = 'block' // Show the selected tab content
  const activeTab = Array.from(tabElements).find(
    tab => tab.textContent.trim() === tabName
  )
  if (activeTab) {
    activeTab.classList.add('active') // Add active class to the clicked tab
  }
}

function printDataframes() {
  const dataframes = document.querySelectorAll('.tab-content div')
  let printContent =
    '<html><head><title>Produção do dia</title>' +
    '<style>' +
    'body { font-family: "Roboto", sans-serif; color: #333; }' +
    '.data { border-radius: 8px; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1); overflow: hidden; max-width: 75%; }' +
    '.data th, .data td { border: none; padding: 4px; font-size: 10px; }' /* Adjusted font size */ +
    '.data th { background-color: #3498db; color: white; font-size: 12px; text-align: center; }' /* Adjusted font size */ +
    '</style>' +
    '</head><body>'
  dataframes.forEach(df => {
    printContent += df.outerHTML // Get the HTML of each dataframe
  })
  printContent += '</body></html>'

  const printWindow = window.open('', '', 'height=600,width=800')
  printWindow.document.write(printContent)
  printWindow.document.close()
  printWindow.print()
}

function printSpecificTable(tableId) {
  const table = document.getElementById(tableId)
  let printContent =
    '<html><head><title>' +
    tableId +
    '</title>' +
    '<style>' +
    'body { font-family: "Roboto", sans-serif; color: #333; }' +
    '.data { border-radius: 8px; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1); overflow: hidden; }' +
    '.data th, .data td { border: none; padding: 4px; font-size: 10px; }' /* Adjusted font size */ +
    '.data th { background-color: #3498db; color: white; font-size: 12px; text-align: center; }' /* Adjusted font size */ +
    '</style>' +
    '</head><body><h1>' + tableId + '</h1>'
  printContent += table.outerHTML // Get the HTML of the specific table
  printContent += '</body></html>'

  // const printWindow = window.open('', '', 'height=600,width=800')
  // printWindow.document.write(printContent)
  // printWindow.document.close()
  // printWindow.print()
  const iframe = document.createElement('iframe')
  iframe.style.position = 'absolute'
  iframe.style.top = '-9999px' // Position off-screen
  iframe.style.left = '-9999px'
  document.body.appendChild(iframe)

  iframe.onload = () => {
    iframe.contentWindow.print()
    iframe.remove() // Clean up the iframe after printing
  }

  iframe.contentDocument.open()
  iframe.contentDocument.write(printContent)
  iframe.contentDocument.close()
}

function copyTableContent(tableId) {
  const table = document.getElementById(tableId)
  let content = ''
  const rows = table.querySelectorAll('tr')

  // Get the total number of rows
  const totalRows = rows.length

  rows.forEach((row, index) => {
    // Skip the header row but include all other rows
    if (index > 0) {
      const cells = row.querySelectorAll('td')
      cells.forEach(cell => {
        content += cell.innerText + '\t' // Add tab between cells
      })
      content = content.trim() + '\n' // New line after each row
    }
  })

  // Copy to clipboard
  navigator.clipboard
    .writeText(content)
    .then(() => {
      showFeedback('Content copied to clipboard!')
    })
    .catch(err => {
      console.error('Error copying text: ', err)
    })
}

function showToast(message, type = 'info', duration = 4000) {
  // Cria o elemento toast
  const toastContainer = document.getElementById('toastContainer')
  if (!toastContainer) {
    console.error('Toast container not found!')
    return
  }

  const toastId = 'toast-' + Date.now()
  const toastElement = document.createElement('div')
  toastElement.className = `toast custom-toast ${type}`
  toastElement.id = toastId

  // Cria o header do toast
  const toastHeader = document.createElement('div')
  toastHeader.className = 'toast-header'

  const title = document.createElement('strong')
  title.className = 'mr-auto'
  title.textContent = getToastTitle(type)

  const closeButton = document.createElement('button')
  closeButton.type = 'button'
  closeButton.className = 'ml-2 mb-1 close'
  closeButton.setAttribute('data-dismiss', 'toast')
  closeButton.setAttribute('aria-label', 'Close')
  closeButton.innerHTML = '<span aria-hidden="true">&times;</span>'
  closeButton.onclick = () => removeToast(toastId)

  toastHeader.appendChild(title)
  toastHeader.appendChild(closeButton)

  // Cria o body do toast
  const toastBody = document.createElement('div')
  toastBody.className = 'toast-body'
  toastBody.textContent = message

  // Monta o toast
  toastElement.appendChild(toastHeader)
  toastElement.appendChild(toastBody)

  // Adiciona ao container
  toastContainer.appendChild(toastElement)

  // Animação de entrada
  setTimeout(() => {
    toastElement.classList.add('show')
  }, 100)

  // Remove automaticamente após a duração
  setTimeout(() => {
    removeToast(toastId)
  }, duration)

  return toastId
}

function getToastTitle(type) {
  switch (type) {
    case 'success':
      return 'Sucesso'
    case 'error':
      return 'Erro'
    case 'warning':
      return 'Atenção'
    case 'info':
    default:
      return 'Informação'
  }
}

function removeToast(toastId) {
  const toast = document.getElementById(toastId)
  if (toast) {
    toast.classList.remove('show')
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast)
      }
    }, 300) // Tempo da transição
  }
}

// Função auxiliar para compatibilidade (mantém funcão showFeedback mas chama showToast)
function showFeedback(message) {
  showToast(message, 'info')
}
// Function to format the date from YYYY-MM-DD HH:MM:SS to dd/mm/aaaa hh:mm
function formatDate(dateString) {
  const date = new Date(dateString)
  const day = String(date.getDate()).padStart(2, '0') // Ensure two digits
  const month = String(date.getMonth() + 1).padStart(2, '0') // Months are zero-based
  const year = date.getFullYear()
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')

  return `${day}/${month}/${year} ${hours}:${minutes}`
}

function setEndDate() {
  const startDate = document.getElementById('start_date').value
  if (startDate) {
    // Create a Date object from the start date string
    const startDateObj = new Date(startDate + 'T00:00:00') // Explicitly set time to 00:00:00

    // Set end datetime to 23:59 on the same day
    const endDateObj = new Date(startDateObj)
    endDateObj.setHours(23, 59, 0, 0)

    // Format end datetime for the input field
    const year = endDateObj.getFullYear()
    const month = String(endDateObj.getMonth() + 1).padStart(2, '0')
    const day = String(endDateObj.getDate()).padStart(2, '0')
    const hours = String(endDateObj.getHours()).padStart(2, '0')
    const minutes = String(endDateObj.getMinutes()).padStart(2, '0')

    const endDateStr = `${year}-${month}-${day}T${hours}:${minutes}`
    document.getElementById('end_datetime').value = endDateStr
  }
}
