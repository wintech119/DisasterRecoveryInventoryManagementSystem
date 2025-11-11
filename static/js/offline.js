class OfflineManager {
  constructor() {
    this.storage = null;
    this.isOnline = navigator.onLine;
    this.isSyncing = false;
    this.syncInterval = null;
    this.statusIndicator = null;
    this.pendingCount = 0;
  }

  async init() {
    this.storage = new OfflineStorage();
    await this.storage.init();
    
    this.setupEventListeners();
    this.updateStatusIndicator();
    this.startPeriodicSync();
    
    if (this.isOnline) {
      await this.syncPendingOperations();
    }
    
    await this.updatePendingCount();
    
    console.log('[Offline Manager] Initialized', { isOnline: this.isOnline });
  }

  setupEventListeners() {
    window.addEventListener('online', () => {
      console.log('[Offline Manager] Back online');
      this.isOnline = true;
      this.updateStatusIndicator();
      this.syncPendingOperations();
    });

    window.addEventListener('offline', () => {
      console.log('[Offline Manager] Gone offline');
      this.isOnline = false;
      this.updateStatusIndicator();
    });

    window.addEventListener('load', () => {
      this.createStatusIndicator();
      this.updateStatusIndicator();
    });
  }

  createStatusIndicator() {
    const nav = document.querySelector('.navbar');
    if (!nav) return;

    const statusContainer = document.createElement('div');
    statusContainer.className = 'offline-status-container';
    statusContainer.innerHTML = `
      <div id="offline-status-pill" class="offline-status-pill" role="status" aria-live="polite">
        <i class="bi bi-circle-fill status-icon"></i>
        <span class="status-text">Online</span>
        <span class="pending-badge badge bg-secondary ms-1 d-none" id="pending-operations-badge">0</span>
      </div>
    `;

    const navbarNav = nav.querySelector('.navbar-nav');
    if (navbarNav) {
      navbarNav.insertBefore(statusContainer, navbarNav.firstChild);
    }

    this.statusIndicator = document.getElementById('offline-status-pill');
    
    this.statusIndicator.addEventListener('click', () => {
      if (this.pendingCount > 0) {
        this.showSyncPanel();
      }
    });
  }

  updateStatusIndicator() {
    if (!this.statusIndicator) return;

    const icon = this.statusIndicator.querySelector('.status-icon');
    const text = this.statusIndicator.querySelector('.status-text');
    
    this.statusIndicator.className = 'offline-status-pill';
    
    if (!this.isOnline) {
      this.statusIndicator.classList.add('status-offline');
      icon.className = 'bi bi-circle-fill status-icon text-danger';
      text.textContent = 'Offline';
      this.statusIndicator.setAttribute('aria-label', 'Offline - Working in offline mode');
    } else if (this.isSyncing) {
      this.statusIndicator.classList.add('status-syncing');
      icon.className = 'bi bi-arrow-repeat status-icon text-warning';
      text.textContent = 'Syncing...';
      this.statusIndicator.setAttribute('aria-label', 'Online - Syncing pending operations');
    } else {
      this.statusIndicator.classList.add('status-online');
      icon.className = 'bi bi-circle-fill status-icon text-success';
      text.textContent = 'Online';
      this.statusIndicator.setAttribute('aria-label', 'Online - All data synced');
    }
  }

  async updatePendingCount() {
    const operations = await this.storage.getPendingOperations();
    this.pendingCount = operations.length;
    
    const badge = document.getElementById('pending-operations-badge');
    if (badge) {
      if (this.pendingCount > 0) {
        badge.textContent = this.pendingCount;
        badge.classList.remove('d-none');
      } else {
        badge.classList.add('d-none');
      }
    }
  }

  startPeriodicSync() {
    this.syncInterval = setInterval(async () => {
      if (this.isOnline && !this.isSyncing) {
        await this.syncPendingOperations();
      }
    }, 30000);
  }

  async queueOperation(type, hubId, payload) {
    const operation = {
      type,
      hub_id: hubId,
      payload,
      user_id: payload.user_id || null
    };

    try {
      const localId = await this.storage.addPendingOperation(operation);
      console.log('[Offline Manager] Operation queued:', { localId, type });
      
      await this.updatePendingCount();
      
      if (this.isOnline) {
        await this.syncPendingOperations();
      }
      
      return { success: true, localId };
    } catch (error) {
      console.error('[Offline Manager] Failed to queue operation:', error);
      return { success: false, error: error.message };
    }
  }

  async syncPendingOperations() {
    if (this.isSyncing || !this.isOnline) return;

    this.isSyncing = true;
    this.updateStatusIndicator();

    try {
      const operations = await this.storage.getPendingOperations();
      
      if (operations.length === 0) {
        this.isSyncing = false;
        this.updateStatusIndicator();
        return;
      }

      console.log(`[Offline Manager] Syncing ${operations.length} operations`);

      for (const operation of operations) {
        try {
          const response = await fetch('/api/offline/sync', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(operation)
          });

          const result = await response.json();

          if (response.ok && result.success) {
            await this.storage.removePendingOperation(operation.local_id);
            console.log('[Offline Manager] Operation synced:', operation.local_id);
          } else {
            await this.storage.addSyncFailure(operation, new Error(result.error || 'Sync failed'));
            await this.storage.removePendingOperation(operation.local_id);
            console.error('[Offline Manager] Operation failed:', result.error);
          }
        } catch (error) {
          console.error('[Offline Manager] Sync error for operation:', operation.local_id, error);
          await this.storage.addSyncFailure(operation, error);
          await this.storage.removePendingOperation(operation.local_id);
        }
      }

      await this.updatePendingCount();
    } catch (error) {
      console.error('[Offline Manager] Sync process error:', error);
    } finally {
      this.isSyncing = false;
      this.updateStatusIndicator();
    }
  }

  async showSyncPanel() {
    const failures = await this.storage.getSyncFailures();
    const pending = await this.storage.getPendingOperations();
    
    let content = '<div class="sync-panel-content">';
    content += '<h5>Sync Status</h5>';
    
    if (pending.length > 0) {
      content += `<p class="text-muted">Pending operations: <strong>${pending.length}</strong></p>`;
      content += '<button class="btn btn-sm btn-primary" onclick="window.offlineManager.syncPendingOperations()">Sync Now</button>';
    }
    
    if (failures.length > 0) {
      content += '<hr>';
      content += '<h6 class="text-danger">Sync Failures</h6>';
      content += '<div class="list-group">';
      failures.forEach(failure => {
        content += `
          <div class="list-group-item">
            <div class="d-flex justify-content-between align-items-start">
              <div>
                <small class="text-muted">${failure.operation.type}</small>
                <br>
                <small class="text-danger">${failure.error}</small>
              </div>
              <button class="btn btn-sm btn-outline-danger" onclick="window.offlineManager.clearFailure(${failure.failure_id})">
                <i class="bi bi-x"></i>
              </button>
            </div>
          </div>
        `;
      });
      content += '</div>';
    }
    
    if (pending.length === 0 && failures.length === 0) {
      content += '<p class="text-success"><i class="bi bi-check-circle me-2"></i>All data synced</p>';
    }
    
    content += '</div>';
    
    const modal = new bootstrap.Modal(document.getElementById('sync-panel-modal') || this.createSyncPanelModal());
    document.getElementById('sync-panel-content').innerHTML = content;
    modal.show();
  }

  createSyncPanelModal() {
    const modalHtml = `
      <div class="modal fade" id="sync-panel-modal" tabindex="-1" aria-labelledby="sync-panel-title" aria-hidden="true">
        <div class="modal-dialog">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title" id="sync-panel-title">Offline Sync Status</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body" id="sync-panel-content"></div>
          </div>
        </div>
      </div>
    `;
    
    const div = document.createElement('div');
    div.innerHTML = modalHtml;
    document.body.appendChild(div.firstElementChild);
    
    return document.getElementById('sync-panel-modal');
  }

  async clearFailure(failureId) {
    await this.storage.clearSyncFailure(failureId);
    this.showSyncPanel();
  }

  async cacheCurrentInventory(hubId, inventoryData) {
    await this.storage.cacheInventory(hubId, inventoryData);
    console.log('[Offline Manager] Inventory cached for hub:', hubId);
  }

  async getCachedInventory(hubId) {
    return await this.storage.getCachedInventory(hubId);
  }

  async storeUserSession(userData) {
    await this.storage.storeSession({
      user_id: userData.user_id,
      username: userData.username,
      role: userData.role,
      hub_id: userData.hub_id,
      expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
    });
  }

  async getStoredSession() {
    const session = await this.storage.getSession();
    
    if (!session) return null;
    
    const expiresAt = new Date(session.expires_at);
    if (expiresAt < new Date()) {
      await this.storage.clearSession();
      return null;
    }
    
    return session;
  }
}

window.offlineManager = new OfflineManager();

document.addEventListener('DOMContentLoaded', () => {
  window.offlineManager.init();
});
