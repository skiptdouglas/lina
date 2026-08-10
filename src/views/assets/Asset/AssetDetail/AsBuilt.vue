<template>
  <TwoCol>
    <DetailCard :title="$t('AsBuiltInfo')" :items="asBuiltItems" />
    <IBox :title="$t('AsBuiltLogs')" style="margin-top: 15px">
      <template #header>
        <div class="clearfix ibox-title">
          <h5>{{ $t('AsBuiltLogs') }}</h5>
          <el-button
            v-if="$hasPerm('assets.change_asset')"
            size="small"
            type="primary"
            style="float: right"
            @click="openLogDialog()"
          >
            {{ $t('Add') }}
          </el-button>
        </div>
      </template>
      <el-table v-loading="logLoading" :data="logs" style="width: 100%">
        <el-table-column prop="date" :label="$t('Date')" width="140" />
        <el-table-column prop="content" :label="$t('Content')" />
        <el-table-column prop="user" :label="$t('User')" width="140" />
        <el-table-column v-if="$hasPerm('assets.change_asset')" :label="$t('Actions')" width="140">
          <template #default="scope">
            <el-button type="text" size="small" @click="openLogDialog(scope.row)">
              {{ $t('Update') }}
            </el-button>
            <el-button type="text" size="small" @click="deleteLog(scope.row)">
              {{ $t('Delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </IBox>
    <template #right>
      <QuickActions :actions="quickActions" type="primary" />
    </template>

    <el-dialog v-model="editVisible" :title="$t('EditAsBuilt')" width="600px">
      <el-form label-width="140px" label-position="left">
        <el-form-item v-for="field in asBuiltFields" :key="field.key" :label="$t(field.label)">
          <el-input v-model="editForm[field.key]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">{{ $t('Cancel') }}</el-button>
        <el-button type="primary" @click="saveAsBuilt">{{ $t('Confirm') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="logDialogVisible"
      :title="logForm.id ? $t('UpdateLog') : $t('AddLog')"
      width="500px"
    >
      <el-form label-width="100px" label-position="left">
        <el-form-item :label="$t('Date')">
          <el-date-picker
            v-model="logForm.date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="$t('Content')">
          <el-input v-model="logForm.content" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="logDialogVisible = false">{{ $t('Cancel') }}</el-button>
        <el-button type="primary" @click="saveLog">{{ $t('Confirm') }}</el-button>
      </template>
    </el-dialog>
  </TwoCol>
</template>

<script>
import DetailCard from '@/components/Cards/DetailCard/index.vue'
import IBox from '@/components/Common/IBox/index.vue'
import { QuickActions } from '@/components/'
import TwoCol from '@/layout/components/Page/TwoColPage.vue'

const AS_BUILT_FIELDS = [
  { key: 'role', label: 'Role' },
  { key: 'runs_on', label: 'RunsOn' },
  { key: 'resources', label: 'Resources' },
  { key: 'os_version', label: 'OSVersion' },
  { key: 'network', label: 'Network' },
  { key: 'dependencies', label: 'Dependencies' },
  { key: 'doc_link', label: 'DocLink' },
  { key: 'last_verified', label: 'LastVerified' },
  { key: 'verified_by', label: 'VerifiedBy' }
]

export default {
  name: 'AsBuilt',
  components: {
    TwoCol,
    DetailCard,
    IBox,
    QuickActions
  },
  props: {
    object: {
      type: Object,
      default: () => ({})
    }
  },
  data() {
    return {
      asBuiltFields: AS_BUILT_FIELDS,
      logs: [],
      logLoading: false,
      editVisible: false,
      editForm: {},
      logDialogVisible: false,
      logForm: {},
      quickActions: [
        {
          title: this.$t('AsBuiltInfo'),
          attrs: {
            type: 'primary',
            label: this.$t('Edit'),
            disabled: !this.$hasPerm('assets.change_asset')
          },
          callbacks: {
            click: () => {
              this.openEditDialog()
            }
          }
        }
      ]
    }
  },
  computed: {
    asBuilt() {
      return this.object.as_built || {}
    },
    asBuiltItems() {
      return this.asBuiltFields.map((field) => {
        return {
          key: this.$t(field.label),
          value: this.asBuilt[field.key] || '-'
        }
      })
    },
    logsUrl() {
      return `/api/v1/assets/asset-as-built-logs/?asset=${this.object.id}`
    }
  },
  mounted() {
    this.getLogs()
  },
  methods: {
    getLogs() {
      this.logLoading = true
      this.$axios
        .get(this.logsUrl)
        .then((res) => {
          const data = Array.isArray(res) ? res : res.results || []
          this.logs = data.slice().sort((a, b) => (a.date < b.date ? 1 : -1))
        })
        .finally(() => {
          this.logLoading = false
        })
    },
    openEditDialog() {
      const form = {}
      this.asBuiltFields.forEach((field) => {
        form[field.key] = this.asBuilt[field.key] || ''
      })
      this.editForm = form
      this.editVisible = true
    },
    saveAsBuilt() {
      this.$axios
        .patch(`/api/v1/assets/assets/${this.object.id}/`, { as_built: this.editForm })
        .then(() => {
          this.object.as_built = { ...this.editForm }
          this.editVisible = false
          this.$message.success(this.$tc('UpdateSuccessMsg'))
        })
        .catch((err) => {
          this.$message.error(this.$tc('UpdateErrorMsg') + ' ' + err)
        })
    },
    openLogDialog(row) {
      this.logForm = row ? { ...row } : { date: '', content: '' }
      this.logDialogVisible = true
    },
    saveLog() {
      const data = {
        asset: this.object.id,
        date: this.logForm.date,
        content: this.logForm.content
      }
      const request = this.logForm.id
        ? this.$axios.patch(`/api/v1/assets/asset-as-built-logs/${this.logForm.id}/`, data)
        : this.$axios.post('/api/v1/assets/asset-as-built-logs/', data)
      request
        .then(() => {
          this.logDialogVisible = false
          this.getLogs()
          this.$message.success(this.$tc('UpdateSuccessMsg'))
        })
        .catch((err) => {
          this.$message.error(this.$tc('UpdateErrorMsg') + ' ' + err)
        })
    },
    deleteLog(row) {
      this.$axios.delete(`/api/v1/assets/asset-as-built-logs/${row.id}/`).then(() => {
        this.getLogs()
        this.$message.success(this.$tc('DeleteSuccessMsg'))
      })
    }
  }
}
</script>

<style lang="scss" scoped></style>
