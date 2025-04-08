import { useState, Fragment } from "react";
import { Text, Box, Button, Table, Title, Card } from "@mantine/core";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  getExpandedRowModel,
  getSortedRowModel,
  SortingState,
} from "@tanstack/react-table";
import { showNotification } from '@mantine/notifications';
import { IconCheck, IconX } from '@tabler/icons-react';

import { Position, Order, TradePair } from "../../types";
import { formatDate, toNormalizePercent } from "../../utils";
import { Orders } from "../Orders";

interface ColumnData {
  trade_pair: TradePair[];
  position_type: string;
  open_ms: number;
  close_ms: number;
  return_at_close: number;
  orders: Order[];
}

const columnHelper = createColumnHelper<ColumnData>();

const columns = (onFlat: (tradePair: string) => void) => [
  columnHelper.accessor("trade_pair", {
    header: "Trade Pair",
    cell: (info) => (
      <Text size="sm">
        {info.getValue()[1]}
      </Text>
    ),
  }),
  columnHelper.accessor("position_type", {
    header: "Position Type",
    cell: (info) => (
      <Text size="sm">
        {info.getValue()}
      </Text>
    ),
  }),
  columnHelper.accessor("open_ms", {
    header: "Open",   
    cell: (info) => (
      <Text size="sm">
        {formatDate(info.getValue())}
      </Text>
    ),
  }),
  columnHelper.accessor("close_ms", {
    header: "Close",
    cell: (info) => (
      <Text size="sm">
        {formatDate(info.getValue())}
      </Text>
    ),
  }),
  columnHelper.accessor("return_at_close", {
    header: "Return",
    cell: (info) => (
      <Text size="sm">
        {toNormalizePercent(info.getValue())}
      </Text>
    ),
  }),
  columnHelper.display({
    id: "actions",
    cell: ({ row }) => (
      <Box ta="right" style={{ display: "flex", gap: 8 }}>
        <Button variant="light" size="sm" color="red" onClick={() => onFlat(row.original.trade_pair[0])}>
          Flat
        </Button>
        <Button variant="light" size="sm" onClick={() => row.toggleExpanded()}>
          View Orders
        </Button>
      </Box>
    ),
  }),
];

interface PositionsProps {
  positions: Position[];
}

export const Positions = ({ positions }: PositionsProps) => {
  const [sorting] = useState<SortingState>([{ id: "open_ms", desc: false }]);

  const handleFlat = async (tradePairId: string) => {
    try {
      const response = await fetch("http://92.43.29.102:28380/api/receive-signal", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          trade_pair: tradePairId,
          order_type: "FLAT",
          leverage: 0.1,
          api_key: "dongnh",
        }),
      });

      if (response.ok) {
        showNotification({
          title: "Success",
          message: `Successfully sent FLAT for ${tradePairId}`,
          color: "green",
          icon: <IconCheck />,
        });
      } else {
        showNotification({
          title: "Failed",
          message: `Failed to send FLAT for ${tradePairId}`,
          color: "red",
          icon: <IconX />,
        });
      }
    } catch (error) {
      showNotification({
        title: "Error",
        message: "Network error",
        color: "red",
        icon: <IconX />,
      });
    }
  };

  const table = useReactTable({
    data: positions,
    columns: columns(handleFlat),
    state: { sorting },
    initialState: {
      pagination: {
        pageIndex: 0,
      },
      sorting,
    },
    getSortedRowModel: getSortedRowModel(),
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  });

  return (
    <Card withBorder>
      <Title order={3} mb="sm">Positions</Title>
      <Table horizontalSpacing="0">
        <Table.Tbody>
          <Table.Tr>
            <Table.Td colSpan={4}>
              <Table>
                <Table.Thead>
                  {table.getHeaderGroups().map((headerGroup) => (
                    <Table.Tr key={headerGroup.id}>
                      {headerGroup.headers.map((header) => (
                        <Table.Th key={header.id}>
                          <Text size="sm" fw={700}>
                            {header.isPlaceholder
                              ? null
                              : flexRender(header.column.columnDef.header, header.getContext())
                            }
                          </Text>
                        </Table.Th>
                      ))}
                    </Table.Tr>
                  ))}
                </Table.Thead>
                <Table.Tbody>
                  {table.getRowModel().rows.map((row) => (
                    <Fragment key={row.id}>
                      <Table.Tr>
                        {row.getVisibleCells().map((cell) => (
                          <Table.Td key={cell.id}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </Table.Td>
                        ))}
                      </Table.Tr>
                      {row.getIsExpanded() && <Orders orders={row.original.orders} />}
                    </Fragment>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.Td>
          </Table.Tr>
        </Table.Tbody>
      </Table>
    </Card>
  );
};
