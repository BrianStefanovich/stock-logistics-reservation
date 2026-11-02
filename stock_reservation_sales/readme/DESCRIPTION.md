This module lets salespeople reserve stock without creating a sales order.

Each reservation creates an internal transfer in the selected warehouse that
reserves the quantities, so they are no longer available for other operations.
Reservations always expire: the salesperson picks the duration in a dropdown
(1 hour up to 1 month, 1 day by default) and a scheduled action releases the
stock once the date has passed.

Salespeople only need the group *Sales Stock Reservations: User: Own
Reservations*; they do not need any other Inventory access rights. The module
makes the *Inventory* app visible to them. Besides *Operations > Sales
Reservations* they will see the read-only *Overview* and *Products* entries.
