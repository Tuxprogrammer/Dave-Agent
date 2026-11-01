// @description: Which chest, drawer, GT super/quantum chest or AE network holds an item, nearest to the asker first, with counts and {waypoint:} links. Loaded chunks only.
// @mode: read
// @side: server
// @timeout_ms: 4000
// @param item: string, required. Item id "modid:name" or "modid:name:meta", "ore:<oredict name>", or a display-name fragment
// @param dim: number. Only this dimension
// @param limit: number. How many places (default 8, max 30)
//
// Sources (shipped tags): GT MTEQuantumChest public mItemStack / mItemCount (GT5-Unofficial 5.09.54.265,
// common/tileentities/storage/MTEQuantumChest.java:24-25); Storage Drawers 2.2.31-GTNH IDrawerGroup.getDrawerCount()
// / getDrawer(int), IDrawer.getStoredItemPrototype() / getStoredItemCount() (api/storage/IDrawerGroup.java:10,15,
// IDrawer.java:18,53), TileEntityController covers its drawers and is skipped; AE2 rv3-beta-1095-GTNH
// TileController.getGridNode(ForgeDirection) -> IGridNode.getGrid() -> IGrid.getCache(IStorageGrid) ->
// getItemInventory().getStorageList() of IAEItemStack (getItemStack(), getStackSize() as a long).

def want = (params.item ?: '').toString().trim()
if (!want) return [error: 'give item']
Integer onlyDim = params.dim != null ? (params.dim as int) : null
int limit = Math.min(30, (params.limit ?: 8) as int)

def wantItem = null; Integer wantMeta = null; Set wantOre = null; String wantName = null
if (want.startsWith('ore:')) {
    wantOre = OreDictionary.getOres(want.substring(4)).collect { [it.getItem(), it.getItemDamage()] } as Set
    if (!wantOre) return [error: "no items with ore name ${want.substring(4)}"]
} else if (want.contains(':')) {
    def parts = want.split(':')
    wantItem = Item.itemRegistry.getObject(parts[0] + ':' + parts[1])
    if (parts.length > 2) wantMeta = parts[2] as int
    if (wantItem == null) return [error: "unknown item id ${parts[0]}:${parts[1]}"]
} else {
    wantName = want.toLowerCase()
}
def matches = { ItemStack s ->
    if (s == null || s.getItem() == null) return false
    if (wantItem != null) return s.getItem().is(wantItem) && (wantMeta == null || s.getItemDamage() == wantMeta)
    if (wantOre != null) return wantOre.any { it[0].is(s.getItem()) && (it[1] == s.getItemDamage() || it[1] == 32767) }
    try { return s.getDisplayName().toLowerCase().contains(wantName) } catch (Throwable e) { return false }
}

def cls = { String n -> try { return dave.cls(n) } catch (Throwable e) { return null } }
def drawerGroup = cls('com.jaquadro.minecraft.storagedrawers.api.storage.IDrawerGroup')
def drawerController = cls('com.jaquadro.minecraft.storagedrawers.block.tile.TileEntityController')
def aeController = cls('appeng.tile.networking.TileController')
def aeStorage = cls('appeng.api.networking.storage.IStorageGrid')
def quantumChest = cls('gregtech.common.tileentities.storage.MTEQuantumChest')
def seenGrids = Collections.newSetFromMap(new IdentityHashMap())

def places = []
def add = { te, int dim, String kind, String name, long count, String itemName ->
    double d2 = (player != null && player.dimension == dim)
        ? dave.dist2(player, te.xCoord + 0.5, te.yCoord + 0.5, te.zCoord + 0.5) : Double.MAX_VALUE
    places << [kind: kind, name: name, item: itemName, count: count, dim: dim, x: te.xCoord, y: te.yCoord,
               z: te.zCoord, distance: d2 == Double.MAX_VALUE ? null : Math.round(Math.sqrt(d2)),
               waypoint: dave.waypoint(te.xCoord, te.yCoord, te.zCoord, dim, name), d2: d2]
}

for (w in dave.worlds()) {
    int dim = w.provider.dimensionId
    if (onlyDim != null && dim != onlyDim) continue
    for (te in dave.tiles(w)) {
        // AE2 network: once per grid, through any controller
        if (aeController != null && aeController.isInstance(te)) {
            try {
                def grid = te.getGridNode(ForgeDirection.UNKNOWN)?.getGrid()
                if (grid != null && seenGrids.add(grid)) {
                    long n = 0; String itemName = null
                    for (ais in grid.getCache(aeStorage).getItemInventory().getStorageList()) {
                        def s = ais.getItemStack()
                        if (matches(s)) { n += ais.getStackSize(); itemName = itemName ?: s.getDisplayName() }
                    }
                    if (n > 0) add(te, dim, 'AE network', 'ME controller', n, itemName)
                }
            } catch (Throwable e) { }
            continue
        }
        if (drawerController != null && drawerController.isInstance(te)) continue
        if (drawerGroup != null && drawerGroup.isInstance(te)) {
            long n = 0; String itemName = null
            for (int i = 0; i < te.getDrawerCount(); i++) {
                def d = te.getDrawer(i)
                def proto = d?.getStoredItemPrototype()
                if (proto != null && matches(proto)) { n += d.getStoredItemCount(); itemName = itemName ?: proto.getDisplayName() }
            }
            if (n > 0) add(te, dim, 'drawer', 'Drawer', n, itemName)
            continue
        }
        long n = 0; String itemName = null; String kind = 'inventory'; String name = te.getClass().getSimpleName()
        if (te.metaClass.respondsTo(te, 'getMetaTileEntity')) {
            def mte = te.getMetaTileEntity()
            if (mte == null) continue
            try { name = mte.getLocalName() } catch (ignored) { }
            if (quantumChest != null && quantumChest.isInstance(mte) && mte.mItemStack != null && matches(mte.mItemStack)) {
                n += mte.mItemCount; itemName = mte.mItemStack.getDisplayName(); kind = 'GT digital chest'
            }
        }
        if (te instanceof IInventory) {
            try { name = (kind == 'inventory' && te.hasCustomInventoryName()) ? te.getInventoryName() : name } catch (ignored) { }
            int size = te.getSizeInventory()
            for (int i = 0; i < size; i++) {
                def s = te.getStackInSlot(i)
                if (matches(s)) { n += s.stackSize; itemName = itemName ?: s.getDisplayName() }
            }
        }
        if (n > 0) add(te, dim, kind, name, n, itemName)
    }
}
places.sort { it.d2 }
[found: places.size(), total: places.sum { it.count } ?: 0, shown: places.take(limit).collect { it.findAll { k, v -> k != 'd2' } },
 note: 'Loaded chunks only. AE networks are counted once per grid at a controller. GT machines list items in their buses too.']
