import { useMemo, useState } from "react"
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import type {
  CellContext,
  ColumnDef,
  RowData,
} from "@tanstack/react-table"

import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

type EditableRow = Record<string, string>

type EditableTableProps = {
  columns: string[]
  rows: EditableRow[]
  onChange: (rows: EditableRow[]) => void
}

declare module "@tanstack/react-table" {
  interface TableMeta<TData extends RowData> {
    updateData: (
      rowIndex: number,
      columnId: keyof TData & string,
      value: string
    ) => void
  }
}

export function EditableTable({
  columns,
  rows,
  onChange,
}: EditableTableProps) {
  const [data, setData] = useState<EditableRow[]>(() =>
    normalizeRows(rows, columns)
  )

  const columnDefs = useMemo<ColumnDef<EditableRow>[]>(
    () =>
      columns.map((column, index) => ({
        accessorKey: column,
        header: column || `Column ${index + 1}`,
        cell: EditableCell,
      })),
    [columns]
  )

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    meta: {
      updateData: (rowIndex, columnId, value) => {
        setData((current) => {
          const next = current.map((row, index) =>
            index === rowIndex ? { ...row, [columnId]: value } : row
          )
          onChange(next)
          return next
        })
      },
    },
  })

  return (
    <div className="max-h-[520px] overflow-auto rounded-lg border">
      <Table className="min-w-max">
        <TableHeader className="sticky top-0 z-10 bg-background">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead
                  className="min-w-44 max-w-72 whitespace-normal align-top"
                  key={header.id}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length > 0 ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    className="min-w-44 max-w-72 whitespace-normal p-1 align-top"
                    key={cell.id}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell
                className="h-24 text-center text-sm text-muted-foreground"
                colSpan={columns.length || 1}
              >
                No rows.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}

function EditableCell({
  getValue,
  row,
  column,
  table,
}: CellContext<EditableRow, unknown>) {
  const initialValue = normalizeCellValue(getValue())
  const [value, setValue] = useState(initialValue)

  return (
    <Input
      aria-label={`${column.id} row ${row.index + 1}`}
      className={cn(
        "h-8 min-w-40 rounded-md border-transparent bg-transparent px-2",
        "font-mono text-xs focus-visible:border-ring"
      )}
      onBlur={() => table.options.meta?.updateData(row.index, column.id, value)}
      onChange={(event) => setValue(event.target.value)}
      value={value}
    />
  )
}

function normalizeRows(rows: EditableRow[], columns: string[]) {
  return rows.map((row) => {
    const normalized: EditableRow = {}
    columns.forEach((column) => {
      normalized[column] = normalizeCellValue(row[column])
    })
    return normalized
  })
}

function normalizeCellValue(value: unknown) {
  return typeof value === "string" ? value : String(value ?? "")
}
