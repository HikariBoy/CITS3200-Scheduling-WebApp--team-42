// Coordinator Modal Management for UC Dashboard
// This file handles the "Manage Coordinators" modal functionality

let selectedCoordinatorId = null;
let coordinatorSearchTimeout = null;
let currentManagingUnitId = null;

// Open the coordinator modal
function openManageCoordinatorsModal() {
  const unitId = getUnitId();
  if (!unitId) {
    alert('No unit selected');
    return;
  }
  
  currentManagingUnitId = unitId;
  document.getElementById('coordinatorUnitId').value = unitId;
  document.getElementById('addCoordinatorModal').style.display = 'flex';
  
  // Load current coordinators
  loadCurrentCoordinators(unitId);
  
  // Reset search
  document.getElementById('coordinatorSearch').value = '';
  document.getElementById('coordinatorSearchResults').style.display = 'none';
  selectedCoordinatorId = null;
  document.getElementById('addCoordinatorBtn').disabled = true;
}

// Close the coordinator modal
function closeCoordinatorModal() {
  document.getElementById('addCoordinatorModal').style.display = 'none';
  currentManagingUnitId = null;
}

// Load current coordinators for the unit
async function loadCurrentCoordinators(unitId) {
  try {
    const response = await fetch(`/unitcoordinator/units/${unitId}/coordinators`);
    const data = await response.json();
    
    const container = document.getElementById('currentCoordinatorsList');
    
    if (!data.ok || !data.coordinators || data.coordinators.length === 0) {
      container.innerHTML = '<p class="text-sm text-gray-500 italic">No coordinators assigned yet</p>';
      return;
    }
    
    const html = data.coordinators.map(coord => `
      <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg border">
        <div>
          <div class="font-medium text-sm">${coord.full_name || coord.email}</div>
          <div class="text-xs text-gray-500">${coord.email}</div>
        </div>
        ${data.coordinators.length > 1 ? `
          <button 
            type="button" 
            onclick="removeCoordinatorFromUnit(${unitId}, ${coord.id}, '${coord.full_name || coord.email}')"
            class="text-red-600 hover:text-red-800 text-sm font-medium px-3 py-1 rounded hover:bg-red-50"
            aria-label="Remove coordinator">
            Remove
          </button>
        ` : '<span class="text-xs text-gray-500 italic">Primary</span>'}
      </div>
    `).join('');
    
    container.innerHTML = html;
  } catch (error) {
    console.error('Error loading coordinators:', error);
    document.getElementById('currentCoordinatorsList').innerHTML = 
      '<p class="text-sm text-red-500">Error loading coordinators</p>';
  }
}

// Search for coordinators
function searchCoordinatorsForModal() {
  const searchInput = document.getElementById('coordinatorSearch');
  const query = searchInput.value.trim();
  const resultsDiv = document.getElementById('coordinatorSearchResults');
  
  if (query.length < 3) {
    resultsDiv.style.display = 'none';
    return;
  }
  
  // Debounce search
  clearTimeout(coordinatorSearchTimeout);
  
  coordinatorSearchTimeout = setTimeout(async () => {
    try {
      const response = await fetch(`/unitcoordinator/search-coordinators?email=${encodeURIComponent(query)}`);
      const data = await response.json();
      
      if (data.ok && data.coordinators && data.coordinators.length > 0) {
        const html = data.coordinators.map(coord => {
          const item = document.createElement('div');
          item.className = 'p-2 hover:bg-gray-100 cursor-pointer border-b';
          item.innerHTML = `<strong>${coord.full_name || coord.email}</strong><br><small>${coord.email}</small>`;
          item.addEventListener('click', () => {
            selectedCoordinatorId = coord.id;
            searchInput.value = coord.email;
            resultsDiv.style.display = 'none';
            document.getElementById('addCoordinatorBtn').disabled = false;
          });
          return item.outerHTML;
        }).join('');
        
        resultsDiv.innerHTML = html;
        resultsDiv.style.display = 'block';
      } else {
        resultsDiv.innerHTML = '<div class="p-2 text-gray-500">No coordinators found</div>';
        resultsDiv.style.display = 'block';
      }
    } catch (error) {
      console.error('Error searching coordinators:', error);
      resultsDiv.innerHTML = '<div class="p-2 text-red-500">Error searching</div>';
      resultsDiv.style.display = 'block';
    }
  }, 300);
}

// Add coordinator to unit
async function addCoordinatorToUnit(event) {
  event.preventDefault();
  
  const unitId = document.getElementById('coordinatorUnitId').value;
  const searchInput = document.getElementById('coordinatorSearch');
  const email = searchInput.value.trim();
  
  if (!selectedCoordinatorId || !unitId) {
    alert('Please select a coordinator');
    return;
  }
  
  try {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    const response = await fetch(`/unitcoordinator/units/${unitId}/add-coordinator`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({ email: email })
    });
    
    const result = await response.json();
    
    if (result.ok) {
      showSimpleNotification(result.message || 'Coordinator added successfully', 'success');
      loadCurrentCoordinators(unitId);
      searchInput.value = '';
      document.getElementById('coordinatorSearchResults').style.display = 'none';
      selectedCoordinatorId = null;
      document.getElementById('addCoordinatorBtn').disabled = true;
    } else {
      showSimpleNotification(result.error || 'Failed to add coordinator', 'error');
    }
  } catch (error) {
    console.error('Error adding coordinator:', error);
    showSimpleNotification('An error occurred while adding the coordinator', 'error');
  }
}

// Remove coordinator from unit
async function removeCoordinatorFromUnit(unitId, coordinatorId, coordinatorName) {
  if (!confirm(`Remove ${coordinatorName} as a coordinator for this unit?`)) {
    return;
  }
  
  try {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    const response = await fetch(`/unitcoordinator/units/${unitId}/coordinators/${coordinatorId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      }
    });
    
    const result = await response.json();
    
    if (result.ok) {
      showSimpleNotification('Coordinator removed successfully', 'success');
      loadCurrentCoordinators(unitId);
    } else {
      showSimpleNotification(result.error || 'Failed to remove coordinator', 'error');
    }
  } catch (error) {
    console.error('Error removing coordinator:', error);
    showSimpleNotification('An error occurred while removing the coordinator', 'error');
  }
}

// Initialize modal event listeners
document.addEventListener('DOMContentLoaded', () => {
  // Close button
  const closeBtn = document.getElementById('closeCoordinatorModal');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeCoordinatorModal);
  }
  
  // Cancel button
  const cancelBtn = document.getElementById('cancelCoordinatorBtn');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', closeCoordinatorModal);
  }
  
  // Search input
  const searchInput = document.getElementById('coordinatorSearch');
  if (searchInput) {
    searchInput.addEventListener('input', searchCoordinatorsForModal);
  }
  
  // Form submission
  const form = document.getElementById('addCoordinatorForm');
  if (form) {
    form.addEventListener('submit', addCoordinatorToUnit);
  }
  
  // Close on overlay click
  const modal = document.getElementById('addCoordinatorModal');
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeCoordinatorModal();
      }
    });
  }
});
